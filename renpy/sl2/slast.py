# Copyright 2004-2014 Tom Rothamel <pytom@bishoujo.us>
#
# Permission is hereby granted, free of charge, to any person
# obtaining a copy of this software and associated documentation files
# (the "Software"), to deal in the Software without restriction,
# including without limitation the rights to use, copy, modify, merge,
# publish, distribute, sublicense, and/or sell copies of the Software,
# and to permit persons to whom the Software is furnished to do so,
# subject to the following conditions:
#
# The above copyright notice and this permission notice shall be
# included in all copies or substantial portions of the Software.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND,
# EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF
# MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND
# NONINFRINGEMENT. IN NO EVENT SHALL THE AUTHORS OR COPYRIGHT HOLDERS BE
# LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY, WHETHER IN AN ACTION
# OF CONTRACT, TORT OR OTHERWISE, ARISING FROM, OUT OF OR IN CONNECTION
# WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE SOFTWARE.

import ast
import renpy.style

from renpy.python import py_compile, py_eval_bytecode, py_exec_bytecode
from renpy.sl2.pyutil import is_constant

# This file contains the abstract syntax tree for a screen language
# screen.

# A serial number that makes each SLNode unique.
serial = 0

# A sentinel used to indicate we should use the value found in the
# expression.
use_expression = object()

# The filename that's currently being compiled.
filename = '<screen language>'

def compile_expr(node):
    """
    Wraps the node in a python AST, and compiles it.
    """

    expr = ast.Expression(body=node)
    ast.fix_missing_locations(expr)
    return compile(expr, filename, "eval")


class SLContext(object):
    """
    A context object that can be passed to the execute methods.
    """

    def __init__(self, parent=None):
        if parent is not None:

            # The scope that python methods are evaluated in.
            self.scope = parent.scope

            # A list of child displayables that will be added to an outer
            # displayable.
            self.children = parent.children

            # A list of keywords.
            self.keywords = parent.keywords

            # The style prefix that is given to children of this displayable.
            self.style_prefix = parent.style_prefix

        else:
            self.scope = { }
            self.children = [ ]
            self.keywords = { }
            self.style_prefix = ""


class SLNode(object):
    """
    The base class for screen language nodes.
    """

    def __init__(self):
        global serial
        serial += 1

        self.serial = serial

    def prepare(self):
        """
        This should be called before the execute code is called, and again
        after init-level code (like the code in a .rpym module or an init
        python block) is called.
        """

        # By default, does nothing.

    def execute(self, context):
        """
        Execute this node, updating context as appropriate.
        """

        raise Exception("execute not implemented by " + type(self).__name__)

    def keywords(self, context):
        """
        Execute this node, updating context.keywords as appropriate.
        """

        # By default, does nothing.
        return

# A sentinel used to indicate a keyword argument was not given.
NotGiven = object()

class SLBlock(object):
    """
    Represents a screen language block that can contain keyword arguments
    and child displayables.
    """

    def __init__(self):

        super(SLBlock, self).__init__()

        # A list of keyword argument, expr tuples.
        self.keyword = [ ]

        # A list of child SLNodes.
        self.children = [ ]


    def prepare(self):

        for i in self.children:
            i.prepare()

        # Compile the keywords.

        keyword_values = { }
        keyword_keys = [ ]
        keyword_exprs = [ ]

        for k, expr in self.keyword:

            node = py_compile(expr, 'eval', ast_node=True)

            if is_constant(node):
                keyword_values[k] = py_eval_bytecode(compile_expr(node))
            else:
                keyword_keys.append(ast.Str(s=k))
                keyword_exprs.append(node)

        if keyword_values:
            self.keyword_values = keyword_values
        else:
            self.keyword_values = None

        if keyword_keys:
            node = ast.Dict(keys=keyword_keys, values=keyword_exprs)
            ast.copy_location(node, keyword_exprs[0])
            self.keyword_exprs = compile_expr(node)
        else:
            self.keyword_exprs = None


    def execute(self, context):

        for i in self.children:
            i.execute(context)

    def keywords(self, context):

        keyword_values = self.keyword_values

        if keyword_values is not None:
            context.keywords.update(keyword_values)

        keyword_exprs = self.keyword_exprs

        if keyword_exprs is not None:
            context.keywords.update(py_eval_bytecode(keyword_exprs))

        style_group = context.keywords.pop("style_group", NotGiven)
        if style_group is not NotGiven:
            if style_group is not None:
                context.style_prefix = style_group + "_"
            else:
                context.style_prefix = ""

        for i in self.children:
            i.keywords(context)



class SLDisplayable(SLBlock):
    """
    A screen language AST node that corresponds to a displayable being
    added to the tree.
    """

    def __init__(self, displayable, scope=False, child_or_fixed=False, style=None, text_style=None, pass_context=False, imagemap=False):
        """
        `displayable`
            A function that, when called with the positional and keyword
            arguments, causes the displayable to be displayed.

        `scope`
            If true, the scope is supplied as an argument to the displayable.

        `child_or_fixed`
            If true and the number of children of this displayable is not one,
            the children are added to a Fixed, and the Fixed is added to the
            displayable.

        `style`
            The base name of the main style.

        `pass_context`
            If given, the context is passed in as the first positonal argument
            of the displayable.

        `imagemap`
            True if this is an imagemap, and should be handled as one.
        """

        super(SLDisplayable, self).__init__()

        self.displayable = displayable

        self.scope = scope
        self.child_or_fixed = child_or_fixed
        self.style = style
        self.pass_context = pass_context

        # Positional argument expressions.
        self.positional = [ ]

        self.imagemap = imagemap


    def prepare(self):

        SLBlock.prepare(self)

        # Prepare the positional arguments.

        exprs = [ ]
        values = [ ]
        has_exprs = False
        has_values = False


        for a in self.positional:
            node = py_compile(a, 'eval', ast_node=True)

            if is_constant(node):
                values.append(py_eval_bytecode(compile_expr(node)))
                exprs.append(ast.Num(n=0))
                has_values = True
            else:
                values.append(use_expression)
                exprs.append(node)
                has_exprs = True

        if has_values:
            self.positional_values = values
        else:
            self.positional_values = None

        if has_exprs:
            t = ast.Tuple(elts=exprs, ctx=ast.Load())
            ast.copy_location(t, exprs[0])
            self.positional_exprs = compile_expr(t)
        else:
            self.positional_exprs = None

    def execute(self, context):

        # Evaluate the positional arguments.

        positional_values = self.positional_values
        positional_exprs = self.positional_exprs

        if positional_values and positional_exprs:
            values = py_eval_bytecode(positional_exprs, context.scope)
            positional = [ b if (a is use_expression) else a for a, b in zip(positional_values, values) ]
        elif positional_values:
            positional = positional_values
        elif positional_exprs:
            positional = py_eval_bytecode(positional_exprs, locals=context.scope)
        else:
            positional = [ ]

        # Create the context.
        ctx = SLContext(context)
        keywords = ctx.keywords = { }
        ctx.children = [ ]

        SLBlock.keywords(self, ctx)

        # Pass the context
        if self.pass_context:
            positional.insert(0, ctx)

        # If we don't know the style, figure it out.
        if ("style" not in keywords) and self.style:
            keywords["style"] = renpy.style.get_style(ctx.style_prefix + self.style) # @UndefinedVariable

        if self.scope:
            keywords["scope"] = ctx.scope

        # Get the widget id and transform, if any.
        widget_id = keywords.pop("id", None)
        transform = keywords.pop("at", None)

        # Create and add the displayables.
        screen = renpy.ui.screen

        if widget_id in screen.widget_properties:
            keywords.update(screen.widget_properties[widget_id])

        d = self.displayable(*positional, **keywords)

        # Evaluate children.
        SLBlock.execute(self, ctx)

        for i in ctx.children:
            d.add(i)

        if widget_id is not None:
            screen.widgets[widget_id] = d

        if transform is not None:
            d = transform(d)

        context.children.append(d)

        if self.imagemap:
            renpy.ui.imagemap_stack.pop()

# TODO: If a displayable is entirely constant, do not re-create it. If a
# tree is entirely constant, reuse it. Be sure to handle imagemaps properly,
# using self.imagemap.

# TODO: Can we gey rid of pass_context?


class SLIf(SLNode):
    """
    A screen language AST node that corresponds to an If/Elif/Else statement.
    """

    def __init__(self):
        """
        An AST node that represents an if statement.
        """

        super(SLIf, self).__init__()

        # A list of entries, with each consisting of an expression (or
        # None, for the else block) and a SLBlock.
        self.entries = [ ]

    def prepare(self):

        # A list of prepared entries, with each consisting of expression
        # bytecode and a SLBlock.
        self.prepared_entries = [ ]

        for cond, block in self.entries:
            if cond is not None:
                cond = py_compile(cond, 'eval')

            block.prepare()

            self.prepared_entries.append((cond, block))

    def execute(self, context):

        for cond, block in self.prepared_entries:
            if cond is None or py_eval_bytecode(cond, locals=context.scope):
                block.execute(context)
                return

    def keywords(self, context):

        for cond, block in self.prepared_entries:
            if cond is None or py_eval_bytecode(cond, locals=context.scope):
                block.keywords(context)
                return



class SLFor(SLBlock):
    """
    The AST node that corresponds to a for statement. This only supports
    simple for loops that assign a single variable.
    """

    def __init__(self, variable, expression):
        super(SLFor, self).__init__()

        self.variable = variable
        self.expression = expression

    def prepare(self):
        node = py_compile(self.expression, 'eval', ast_node=True)

        if is_constant(node):
            self.expression_value = py_eval_bytecode(compile_expr(node))
            self.expression_expr = None
        else:
            self.expression_value = None
            self.expression_expr = compile_expr(node)

        SLBlock.prepare(self)

    def execute(self, context):

        variable = self.variable
        expr = self.expression_expr

        if expr is not None:
            value = py_eval_bytecode(expr, locals=context.scope)
        else:
            value = self.expression_value

        for i in value:
            context.scope[variable] = i

            SLBlock.execute(self, context)

    def keywords(self, context):
        return


class SLPython(SLNode):

    def __init__(self, code):
        super(SLNode, self).__init__()

        # A pycode object.
        self.code = code

    def execute(self, context):
        py_exec_bytecode(self.code.bytecode, locals=context.scope)


class SLPass(SLNode):

    def execute(self, context):
        return


class SLDefault(SLNode):

    def __init__(self, variable, expression):
        self.variable = variable
        self.expression = expression

    def prepare(self):
        self.expr = py_compile(self.expression, 'eval')

    def execute(self, context):
        scope = context.scope
        variable = self.variable

        if variable in scope:
            return

        scope[variable] = py_eval_bytecode(self.expr, locals=scope)
