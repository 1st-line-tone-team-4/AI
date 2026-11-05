import ast
import re
import unicodedata
from fractions import Fraction

from ai.models import AnswerVerification, MultipleChoiceAnswer, StoredQuestion


def normalize_answer(value: str) -> str:
    return re.sub(r"\s+", " ", unicodedata.normalize("NFKC", value)).strip().lower()


def numeric(value: str) -> Fraction:
    if not re.fullmatch(r"[-+]?\d{1,18}(?:\.\d{1,12}|/\d{1,18})?", value.strip()):
        raise ValueError("Only plain numbers and fractions are supported.")
    return Fraction(value.strip())


def arithmetic(expression: str) -> Fraction:
    if len(expression) > 200:
        raise ValueError("Expression too long.")
    tree = ast.parse(expression, mode="eval")
    if len(list(ast.walk(tree))) > 60:
        raise ValueError("Expression too complex.")

    def visit(node):
        if isinstance(node, ast.Constant) and type(node.value) in (int, float):
            value = numeric(str(node.value))
        elif isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.UAdd, ast.USub)):
            value = visit(node.operand) * (-1 if isinstance(node.op, ast.USub) else 1)
        elif isinstance(node, ast.BinOp):
            left, right = visit(node.left), visit(node.right)
            if isinstance(node.op, ast.Add):
                value = left + right
            elif isinstance(node.op, ast.Sub):
                value = left - right
            elif isinstance(node.op, ast.Mult):
                value = left * right
            elif isinstance(node.op, ast.Div):
                value = left / right
            elif isinstance(node.op, ast.Pow) and right.denominator == 1 and abs(right) <= 10:
                value = left ** int(right)
            else:
                raise ValueError("Unsupported arithmetic operator.")
        else:
            raise ValueError("Only bounded numeric arithmetic is supported.")
        if abs(value.numerator) > 10**18 or value.denominator > 10**18:
            raise ValueError("Arithmetic magnitude exceeds limits.")
        return value

    return visit(tree.body)


def verify_answer(stored: StoredQuestion) -> AnswerVerification:
    scope = (
        "Arithmetic consistency only; word-problem meaning, algebra and proofs are not verified."
    )
    if stored.arithmetic_expression is None:
        return AnswerVerification(status="not_verified", scope=scope)
    answer = stored.correct_answer
    if isinstance(answer, MultipleChoiceAnswer):
        answer = next(
            o.text for o in stored.question.options if o.id == answer.selected_option_ids[0]
        )
    else:
        answer = answer.text
    try:
        equal = arithmetic(stored.arithmetic_expression) == numeric(answer)
    except (ValueError, SyntaxError, ZeroDivisionError, OverflowError, RecursionError):
        return AnswerVerification(status="not_verified", scope=scope)
    return AnswerVerification(status="consistent" if equal else "inconsistent", scope=scope)
