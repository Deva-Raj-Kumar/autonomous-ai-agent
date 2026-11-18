"""Property-based security tests (Hypothesis).

An example-based test checks the inputs WE thought of. A property test states a rule
("whatever the input, the calculator returns a number or a ToolError") and Hypothesis
generates thousands of inputs trying to break it, then SHRINKS a failure to the
simplest input that still fails. Great for parsers, sanitizers and anything that
handles hostile text.
"""

import string
import tempfile
import time
from pathlib import Path

from fastapi import HTTPException
from hypothesis import HealthCheck, example, given, settings
from hypothesis import strategies as st

from app.api.routes import safe_upload_name
from app.auth.security import InvalidTokenError, TokenConfig, decode_access_token
from app.rag.ingestion import ALLOWED_EXTENSIONS
from app.safety.approval import fingerprint
from app.safety.injection import scan_for_injection
from app.safety.secrets import contains_secret, redact_secrets
from app.tools.base import ToolError
from app.tools.calculator import safe_eval
from app.tools.file_reader import resolve_safe_path

THOROUGH = settings(max_examples=400, deadline=None, suppress_health_check=[HealthCheck.too_slow])
# Fewer examples where each one touches the file system (Path.resolve is slow on Windows).
FILESYSTEM = settings(max_examples=150, deadline=None, suppress_health_check=[HealthCheck.too_slow])

# Expression pieces: real math AND attack material (dunder access, calls, attributes).
EXPRESSION_TOKENS = st.sampled_from([
    "1", "2", "9", "0", "45000", "1e308", ".5", "+", "-", "*", "/", "//", "%", "**", "(", ")", ",",
    "sqrt", "round", "abs", "max", "min", "pi", "__import__", "os", ".", "system", "[", "]", "lambda",
    "x", ":", "'a'", "__class__", "__subclasses__", "open", "exec", " ", "<", "==", "not", "if", "else",
])


# ---------------------------------------------------------------- calculator
@THOROUGH
@given(st.lists(EXPRESSION_TOKENS, max_size=40).map("".join))
@example("__import__('os').system('echo hacked')")
@example("().__class__.__base__.__subclasses__()")
@example("9**9**9**9")
@example("-" * 400 + "1")
@example("(" * 300 + "1" + ")" * 300)
def test_calculator_returns_a_number_or_a_tool_error_quickly(expression: str) -> None:
    started = time.perf_counter()
    try:
        result = safe_eval(expression)
    except ToolError:
        result = None
    assert time.perf_counter() - started < 1.0  # no input may hang the agent (DoS)
    assert result is None or isinstance(result, int | float)


# ------------------------------------------------------------- file names
@THOROUGH
@given(st.text(max_size=80))
@example("../../app/main.py")
@example("C:\\Windows\\win.ini")
@example("..\\..\\.env.txt")
@example(".hidden.md")
@example("report.pdf\x00.exe")
def test_upload_names_are_reduced_to_a_bare_allowed_name(filename: str) -> None:
    try:
        name = safe_upload_name(filename)
    except HTTPException as exc:
        assert exc.status_code in (400, 415)
        return
    assert "/" not in name and "\\" not in name and "\x00" not in name
    assert not name.startswith(".") and name not in ("", ".", "..")
    assert "." + name.rsplit(".", 1)[-1].lower() in ALLOWED_EXTENSIONS


_DOCS = Path(tempfile.mkdtemp(prefix="jail_")) / "documents"
(_DOCS / "sub").mkdir(parents=True)
(_DOCS / "notes.txt").write_text("ok", encoding="utf-8")
(_DOCS.parent / "secret.txt").write_text("outside the jail", encoding="utf-8")
PATH_PARTS = st.sampled_from(["..", ".", "sub", "notes.txt", "secret.txt", "/", "\\", "C:", "~", "%2e%2e", " "])


@FILESYSTEM
@given(st.lists(PATH_PARTS, max_size=8).map("".join))
@example("../secret.txt")
@example("sub/../../secret.txt")
@example(str(_DOCS.parent / "secret.txt"))
def test_file_reader_never_leaves_the_documents_folder(requested: str) -> None:
    try:
        resolved = resolve_safe_path(_DOCS, requested)
    except ToolError:
        return
    assert resolved.is_relative_to(_DOCS.resolve())


# --------------------------------------------------------------- secrets
KEY_BODY = st.text(alphabet=string.ascii_letters + string.digits + "_-", min_size=35, max_size=60)
WORDS = st.text(alphabet=string.ascii_letters + string.digits + " .,:;!?()\n", max_size=60)


@THOROUGH
@given(prefix=WORDS, body=KEY_BODY, suffix=WORDS, kind=st.sampled_from(["AIza", "sk-", "tvly-"]))
def test_api_keys_are_always_redacted(prefix: str, body: str, suffix: str, kind: str) -> None:
    key = kind + body
    text = f"{prefix} {key} {suffix}"

    assert key not in redact_secrets(text)
    assert contains_secret(text)


@THOROUGH
@given(st.text(max_size=300))
def test_redaction_is_idempotent(text: str) -> None:
    once = redact_secrets(text)
    assert redact_secrets(once) == once


# ------------------------------------------------- regex denial of service
ADVERSARIAL = st.sampled_from(["password", "token = ", "1 ", "1-", "a:", "://x:", "ignore ", "previous ", "@", " "])


@settings(max_examples=150, deadline=None)
@given(st.lists(ADVERSARIAL, min_size=50, max_size=800).map("".join))
def test_scanners_stay_fast_on_hostile_text(text: str) -> None:
    # Badly written regexes can take exponential time on crafted input (ReDoS), freezing
    # the server. Every scanner here runs on untrusted text.
    started = time.perf_counter()
    redact_secrets(text)
    contains_secret(text)
    scan_for_injection(text)
    assert time.perf_counter() - started < 0.5


# ------------------------------------------------------- tokens & audit
@THOROUGH
@given(st.text(max_size=300))
def test_any_garbage_token_is_just_invalid(token: str) -> None:
    try:
        decode_access_token(token, TokenConfig(secret="s" * 40))
    except InvalidTokenError:
        return
    raise AssertionError("a random string was accepted as a token")


JSON_VALUES = st.recursive(
    st.none() | st.booleans() | st.integers() | st.text(max_size=20),
    lambda inner: st.lists(inner, max_size=4) | st.dictionaries(st.text(max_size=8), inner, max_size=4),
    max_leaves=10,
)


@settings(max_examples=150, deadline=None)
@given(st.dictionaries(st.text(max_size=10), JSON_VALUES, max_size=6), st.randoms())
def test_approval_fingerprint_ignores_key_order(arguments: dict, rng) -> None:
    items = list(arguments.items())
    rng.shuffle(items)

    assert fingerprint(dict(items)) == fingerprint(arguments)
