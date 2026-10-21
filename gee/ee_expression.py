"""A bounded arithmetic parser for Image.parseExpression descriptions."""
import ast
import re

from .ee_translate import Image, Pixel, as_image, binary, const, fail, pairs, unary


TOKEN = re.compile(r'''\s*(?:(\d+(?:\.\d*)?(?:[eE][+-]?\d+)?|\.\d+(?:[eE][+-]?\d+)?)|([A-Za-z_][A-Za-z_0-9]*)|("(?:\\.|[^"\\])*"|'(?:\\.|[^'\\])*')|(\*\*|&&|\|\||==|!=|<=|>=|[+*/%<>()\[\].,:?!\-=]))''')
PRECEDENCE = {"||": 1, "&&": 2, "==": 3, "!=": 3, "<": 4, "<=": 4, ">": 4, ">=": 4,
              "+": 5, "-": 5, "*": 6, "/": 6, "%": 6, "**": 7}
OPS = {"+": "add", "-": "subtract", "*": "multiply", "/": "divide", "%": "mod", "**": "power",
       "==": "eq", "!=": "neq", "<": "lt", "<=": "lte", ">": "gt", ">=": "gte", "&&": "and", "||": "or"}


class Parser:
    def __init__(self, text, variables, default, translator):
        if not isinstance(text, str) or len(text) > 20000:
            fail("Image expression must be a string of at most 20000 characters")
        self.tokens = []
        pos = 0
        text = text.strip()
        while pos < len(text):
            match = TOKEN.match(text, pos)
            if not match:
                fail(f"Unsupported Image.expression syntax near character {pos}")
            number, name, string, symbol = match.groups()
            if number is not None: self.tokens.append(("number", float(number)))
            elif name is not None: self.tokens.append(("name", name))
            elif string is not None: self.tokens.append(("string", ast.literal_eval(string)))
            else: self.tokens.append(("symbol", symbol))
            pos = match.end()
        if len(self.tokens) > 4000: fail("Image.expression has too many tokens")
        self.tokens.append(("end", "<end>"))
        self.i = 0
        self.variables = variables
        self.default = default
        self.t = translator
        self.depth = 0

    def peek(self): return self.tokens[self.i][1]

    def take(self, expected=None):
        token = self.tokens[self.i]
        if expected is not None and token[1] != expected:
            fail(f"Expected {expected!r} in Image.expression")
        self.i += 1
        return token

    def parse(self):
        assigned = None
        if self.tokens[0][0] == "name" and self.tokens[1][1] == "=":
            assigned = self.take()[1]
            self.take("=")
        result = as_image(self.expression())
        self.take("<end>")
        if assigned is not None:
            if len(result.bands) != 1: fail("Expression assignment can only name a single-band result")
            result = self.t.select(result, [0], [assigned])
        return result

    def expression(self, minimum=0):
        self.depth += 1
        if self.depth > 64: fail("Image.expression nesting exceeds 64")
        token = self.take()
        if token[1] in {"-", "+", "!"} and token[0] == "symbol":
            operand = self.expression(7)
            left = binary(0, operand, "subtract") if token[1] == "-" else unary(operand, "not") if token[1] == "!" else operand
        elif token[1] == "(":
            left = self.expression(); self.take(")")
        elif token[0] == "number": left = token[1]
        elif token[0] == "name":
            name = token[1]
            if self.peek() == "(":
                self.take("("); args = []
                if self.peek() != ")":
                    while True:
                        if self.tokens[self.i][0] == "string": args.append(self.take()[1])
                        else: args.append(self.expression())
                        if self.peek() != ",": break
                        self.take(",")
                self.take(")")
                left = self.call(name, args)
            elif name in self.variables: left = self.variables[name]
            elif name in {"true", "false"}: left = name == "true"
            else: fail(f"Unknown Image.expression variable: {name}")
        else:
            fail("Expected a number, variable or arithmetic expression")
        while True:
            symbol = self.peek()
            if symbol == ".":
                self.take(".")
                name_token = self.take()
                if name_token[0] != "name": fail("Expected image band name after dot")
                left = self.t.select(as_image(left), [name_token[1]])
                continue
            if symbol == "[":
                self.take("["); selectors = []
                while True:
                    typ, value = self.take()
                    if typ == "number" and int(value) == value: value = int(value)
                    elif typ != "string": fail("Image band indexing requires a static name or integer")
                    selectors.append(value)
                    if self.peek() != ",": break
                    self.take(",")
                self.take("]")
                left = self.t.select(as_image(left), selectors)
                continue
            prec = PRECEDENCE.get(symbol, -1)
            if prec < minimum: break
            self.take()
            right = self.expression(prec if symbol == "**" else prec+1)
            left = binary(left, right, OPS[symbol])
        if minimum == 0 and self.peek() == "?":
            self.take("?"); yes = self.expression(); self.take(":"); no = self.expression()
            yes, no, matched = pairs(yes, no)
            condition = as_image(left)
            if len(condition.bands) not in (1, len(matched)): fail("Ternary condition band count mismatch")
            bands = [(n, Pixel("if", (condition.bands[0 if len(condition.bands)==1 else i][1], y, nvalue)))
                     for i, (n, y, nvalue) in enumerate(matched)]
            left = Image(bands, dict(yes.props), yes.source or no.source or condition.source,
                         yes.mapped or no.mapped or condition.mapped)
        self.depth -= 1
        return left

    def call(self, name, args):
        if name == "b":
            image = self.variables.get(self.default)
            if image is None: fail("Missing default expression Image")
            if not args: return image
            selectors = []
            for value in args:
                if isinstance(value, float) and value.is_integer(): value = int(value)
                if not isinstance(value, (str, int)): fail("b() requires static band names or indices")
                selectors.append(value)
            return self.t.select(image, selectors)
        unary_functions = {"abs": "absolute", "sqrt": "sqrt", "log": "log", "log10": "log10", "exp": "exp", "round": "round", "floor": "floor", "ceil": "ceil", "sin": "sin", "cos": "cos", "tan": "tan"}
        if name in unary_functions and len(args) == 1: return unary(args[0], unary_functions[name])
        if name in {"pow", "min", "max"} and len(args) == 2:
            return binary(args[0], args[1], {"pow": "power", "min": "min2", "max": "max2"}[name])
        fail(f"Unsupported Image.expression function or arity: {name}")


def parse_expression(text, variables, default, translator):
    return Parser(text, variables, default, translator).parse()
