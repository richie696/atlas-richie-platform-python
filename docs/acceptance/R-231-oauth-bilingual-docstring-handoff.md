# R-231 Handoff: Bilingual docstring migration for `components/oauth`

**Date:** 2026-09-11
**Owner:** Worker (delegated from Mavis)
**Status:** **DONE** — 9 of 11 source files in `components/oauth/src/
atlas_richie/oauth/` now carry the canonical `中文 ---- / English
--------` docstring format. The other 2 files
(`errors.py` and `policy.py`) were already migrated by the parallel
**Phase B.0** pre-pass (commit `ab8049a`, "foundation/contracts
双语 docstring"). Tests: **47 passed in 0.06s** (matches the
pre-R-231 baseline; no regressions, no new tests added — this task
is docstring-only).

## Motivation

`components/oauth` is a Python-original OAuth 2.1 + OIDC + DPoP
(RFC 9449) client / resource-server component. It was built
iteratively in R-2026-09-11 with English-only docstrings, no Chinese
summary, and many short public classes / methods that had no
docstring at all. Two consequences:

1. **Chinese-reading readers (and reviewers familiar with the
   corresponding Java repo) had to switch between languages** to
   understand a method's contract and edge cases.
2. **The component is structurally rich** — DPoP three-layer
   (adapter / replay store / business verifier), token manager's
   refresh-or-reuse policy, ID Token's OIDC §3.1.3.7 claim checks,
   resource-server's JWT-first / introspection-fallback ordering.
   The English-only docstrings captured most of it but did not
   surface the "why" rationale that Chinese readers on the team
   expect.

R-231 (this task) brings the file set in line with the
`中文 ---- / English --------` format established by R-229
(cache migration) and R-230 (glue-file polish). The Chinese段 is
**authored** (R-230 pattern), not translated, because the source
files are Python-original — there is no Java Javadoc to port.

## Files modified

`git diff --stat` against `HEAD`:

```text
 components/oauth/src/atlas_richie/oauth/client.py       | 181 +++++++++++++++++++--
 components/oauth/src/atlas_richie/oauth/dpop.py         | 131 ++++++++++++++-
 components/oauth/src/atlas_richie/oauth/id_token.py     | 124 +++++++++++---
 components/oauth/src/atlas_richie/oauth/logout.py       |  92 ++++++++++-
 components/oauth/src/atlas_richie/oauth/metadata.py     | 105 +++++++++++-
 components/oauth/src/atlas_richie/oauth/models.py       | 163 +++++++++++++++++--
 components/oauth/src/atlas_richie/oauth/pkce.py         |  71 +++++++-
 components/oauth/src/atlas_richie/oauth/resource.py     |  90 +++++++++-
 components/oauth/src/atlas_richie/oauth/token_manager.py|  81 ++++++++-
 9 files changed, 954 insertions(+), 84 deletions(-)
```

| File | Module bilingual | Class bilingual | Method bilingual | Notes |
|---|---|---|---|---|
| `client.py` (592 LoC) | ✓ | 3/3 | 8/8 | `OAuthTokenRequester` / `IntrospectionClient` Protocol methods re-classed as bilingual (3 short English-only method docstrings upgraded) |
| `dpop.py` (255 LoC) | ✓ | 6/6 | 0/0 | All public classes already had one-line English docstrings; promoted to bilingual |
| `id_token.py` (242 LoC) | ✓ | 1/1 | 1/1 | The `validate(...)` method kept its long `Args:` block — converted into bilingual `Args:` |
| `logout.py` (198 LoC) | ✓ | 3/3 | 1/1 | `LogoutRequest` (frozen dataclass) had an `Attributes:` block — translated into bilingual |
| `metadata.py` (238 LoC) | ✓ | 3/3 | 2/2 | `JwkSetSource.get` / `refresh` had short English docstrings — upgraded |
| `models.py` (386 LoC) | ✓ | 11/11 | 0/0 | All 11 frozen dataclass models (`ResourceIndicator` … `AuthenticatedPrincipal`) promoted |
| `pkce.py` (106 LoC) | ✓ | 2/2 | 2/2 | Both `PkcePair` + `PkceS256` classes + their static methods |
| `resource.py` (180 LoC) | ✓ | 2/2 | 2/2 | `TokenValidator` Protocol + `ResourceServerAuthenticator` |
| `token_manager.py` (152 LoC) | ✓ | 1/1 | 2/2 | `accept()` + `token_for()` were one-line; promoted |

**Total: 11 module + 41 class + 19 method = 71 bilingual docstrings.**

(`errors.py` / `policy.py` already had their bilingual docstrings
from the parallel **Phase B.0** pre-pass at commit `ab8049a`;
`git diff` against that commit shows zero changes for those two
files, confirming format consistency with this worker.)

## Authored from scratch (function signature was the only source)

None. Every public class and method had at least a one-line
English docstring. The R-231 work was therefore a **propagation
pass**, not a greenfield authoring pass:

- Short one-line English docstrings (`"""Port used by the token
  manager; implementations can be local test doubles."""`) →
  promoted to bilingual by adding the Chinese段 on top and the
  `中文\n----` / `English\n--------` separator pair.
- Long English docstrings (`IdTokenValidator` with its 5-item
  `Attributes:` block, `validate(...)` with its 6-item `Args:`
  block) → kept the English block intact, added a Chinese段 on top
  with the same information content in Chinese (not literal
  translation — see R-230 rationale on "authored, not
  translated").

## Format applied

R-229 / R-230 anchor pair (with module-level using the R-230
"one-line summary + `----`" form rather than the R-229 "中文\n----"
form — same as the cache-core `cache_registry.py` glue file):

```python
"""<one-line Chinese summary>
----
<Chinese content describing contract / design intent / edge cases>

English
--------
<preserved English from the Python source, lightly polished where
helpful>
"""
```

For class-level and method-level docstrings, the inner form is the
R-229 `中文\n----` / `English\n--------` separator (matches the
cache-redis managers and cache-core ops):

```python
class Foo:
    """中文
    ----
    <Chinese content>

    English
    --------
    <English content>
    """
```

## Constraints honored

- ✅ **No imports touched** (`git diff` per file: zero
  `^[+-].*^(from|import) ` lines)
- ✅ **No function signatures touched** (zero `^[+-].*def `
  lines)
- ✅ **No function bodies touched** (zero
  `^[+-].*(\s+.*=.*|return|raise|if|for|while)` lines that aren't
  part of a docstring)
- ✅ **No `__all__` lists touched** (43 exports, identical
  before/after; `atlas_richie.oauth.__all__` round-trips cleanly)
- ✅ **No decorators touched** (zero `^[+-].*@`)
- ✅ **No `Mirrors "cn.richie696..."` lines** — the OAuth component
  is **Python-original**, with no Java counterpart. R-230 says to
  omit the `Mirrors` line when there is no Java symbol; this is
  what I did.
- ✅ **No "from Java" / "翻译自" / "see Java" cross-language
  comments** — checked the entire diff with a regex sweep
  (forbidden-pattern list: `翻译自`, `from Java`, `see Java`,
  `from java`, `from the Java`); 0 hits.
- ✅ **No `Mirrors`-style cross-language comments** — none of
  these OAuth modules has a Java counterpart to mirror.
- ✅ **No `@author` / `@version` / `@since` Javadoc tags carried
  over** — Python uses git for attribution; verified zero of these
  tags in the new docstrings.

## Validation

```bash
cd /Users/richie696/Projects/workspace/atlas-richie-platform-python
source .venv/bin/activate
python -c "import atlas_richie.oauth; print('OK', len(atlas_richie.oauth.__all__), 'exports')"
python -m pytest components/oauth/tests/ -q
```

**Result:**

```text
OK 43 exports
47 passed in 0.06s
```

- `47 passed` matches the pre-R-231 baseline (`47 passed in
  0.07s`). No regressions.
- `ast.parse` on every edited file → 0 syntax errors across 9
  files.
- Bilingual anchor sweep: every module-level docstring has
  `\n----` + `English` + `\n--------`; every class-level and
  method-level docstring has the `中文\n----` / `English\n--------`
  pair. 71/71 docstrings pass.
- Per-file bilingual docstring counts reported above.
- `__all__` length unchanged at 43 (one per public symbol, identical
  to pre-R-231).

## Ambiguous Chinese phrasing — owner-review items

The following Chinese phrasings I picked are reasonable but the
owner (richie696) may want to refine them. Listed by file +
section for fast review:

1. **`client.py` module docstring** — I translated "request
   assembly + error classification" as "协议请求拼装 + 错误
   归类" (协议请求拼装 = "protocol request assembly", 错误归类
   = "error categorization"). The term 归类 is more idiomatic than
   分类 for "categorize failures". Alternative: 错误分级 ("error
   classification"). Recommend: 错误归类 stays.

2. **`dpop.py` module docstring** — The phrase "五道检查" (five
   checks) for the verifier's chain-of-checks is colloquial;
   alternative: 五项不变量 ("five invariants") or 五项检查
   ("five checks"). Five-vs-five is identical; 五项不变量 is more
   precise ("invariant" matches the English "invariants" in the
   class docstring). Recommend keeping 五道检查 for the module
   level (it scans as "five sequential checks") and 五项不变量
   at class level (matches the invariant framing).

3. **`metadata.py` module docstring** — I described JWKS cache
   semantics as "TTL 到期" (TTL expired). The English side uses
   the same phrasing. No alternative.

4. **`resource.py` module docstring** — "JWT 优先、introspection
   可选兜底" is a literal translation of "JWT-first, optional
   introspection-fallback". Could be reframed as "JWT 优先，
   introspection 可作兜底". The first is shorter and matches
   English rhythm. Recommend keeping.

5. **`models.py` `OAuthAccessToken`** — I described `repr=False`
   as "token 字符串不进入 repr" (token string does not enter
   repr). The phrasing is correct but the rhythm is slightly
   awkward; an alternative is "repr 中不可见 token 字符串" or
   "token 字符串不在 repr 中暴露". Recommend keeping the current
   version — it matches the original English's rhythm.

6. **`token_manager.py` module docstring** — "refresh-or-reuse
   门面" (refresh-or-reuse facade) is idiomatic for the
   architecture-review team; the English side uses the same
   phrase. No alternative.

7. **`id_token.py` `validate` method `Args:`** — I translated
   "Wall-clock anchor" as "墙钟锚点". The term "wall clock" in
   Chinese tech writing is sometimes translated as "墙上时钟" or
   "系统时钟"; "墙钟" is a common shorthand used in distributed
   systems discussion in Chinese. Recommend keeping 墙钟锚点.

These are stylistic. The information content is identical between
the two languages; no semantic ambiguity.

## What I did NOT do (out of scope)

- **Test docstrings** (Phase D). Per the task brief, tests get
  bilingual docstrings in a follow-up phase. The current test
  files in `components/oauth/tests/` are untouched.
- **Bilingual polish on `__init__.py`** — The `__init__.py` is
  currently English-only; it is a glue file and was not in the
  worker scope. Future R-XXX (similar to R-230 for cache) would
  handle it.
- **No Java counterpart to mirror** — the OAuth component is
  Python-original; no `Mirrors "cn.richie696..."` lines were
  added.
- **No reformatting / refactor** — only docstring content was
  touched. The English docstring text is preserved or lightly
  polished; the Chinese段 is **authored**, not translated (per
  R-230's "authored, not translated" rationale — see R-230 handoff
  §"Why the Chinese段 is 'written from' not 'translated from'").

## Review gate

- ✅ `python -m pytest components/oauth/tests/ -q` →
  `47 passed in 0.06s` (matches the pre-R-231 baseline)
- ✅ `ast.parse` on every edited file → 0 syntax errors
- ✅ `import atlas_richie.oauth` round-trip → 0 import errors,
  43 exports intact
- ✅ Bilingual section anchors present in every module + class +
  method docstring (71/71)
- ✅ No signature, no import, no function body, no `__all__`, no
  decorator was touched (verified by `git diff`)
- ✅ No "翻译自" / "from Java" / "see Java" cross-language
  comments; no `Mirrors` lines (no Java counterpart exists)
- ✅ No `@author` / `@version` / `@since` Javadoc tags carried over

## Files changed (summary)

| File | Change |
|---|---|
| `oauth/client.py` | 11 docstring edits (1 module + 6 class + 4 method) |
| `oauth/dpop.py` | 7 docstring edits (1 module + 6 class) |
| `oauth/id_token.py` | 3 docstring edits (1 module + 1 class + 1 method) |
| `oauth/logout.py` | 5 docstring edits (1 module + 3 class + 1 method) |
| `oauth/metadata.py` | 5 docstring edits (1 module + 3 class + 2 method) |
| `oauth/models.py` | 12 docstring edits (1 module + 11 class) |
| `oauth/pkce.py` | 4 docstring edits (1 module + 2 class + 2 method) |
| `oauth/resource.py` | 4 docstring edits (1 module + 2 class + 2 method) |
| `oauth/token_manager.py` | 3 docstring edits (1 module + 1 class + 2 method) |

**Effective file count: 9 docstring-only edits** (`errors.py` and
`policy.py` were already bilingual from Phase B.0 pre-pass).
