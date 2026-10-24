"""Direct Mode backend for `gl.eq_principle.prompt_non_comparative`.

genlayer-test's Direct Mode does not implement the `ExecPromptTemplate` gl_call
that the SDK's `prompt_non_comparative` issues, so `mock_llm` alone cannot drive
it. This shim answers that one call from `direct_vm.mock_llm` mocks. The SDK's
own leader/validator code (`run_nondet`, `_decode_nondet`, closures) is NOT
replaced - only the LLM backend is mocked, as `mock_llm` is meant to do.

Rendered prompts that `mock_llm` patterns are matched against:
  leader:    "[EqNonComparativeLeader]\\n<task>\\n<input>\\n<criteria>"
  validator: "[EqNonComparativeValidator] output=<repr(leader output)>\\n<task>\\n<input>\\n<criteria>"
Validator mocks must answer "true" or "false".
"""

import pytest
from gltest.direct import wasi_mock

LEADER = "[EqNonComparativeLeader]"
VALIDATOR = "[EqNonComparativeValidator]"


@pytest.fixture(autouse=True)
def _prompt_template_backend(monkeypatch, direct_vm):
    original = wasi_mock._handle_gl_call

    def handle(vm, request):
        if isinstance(request, dict) and "ExecPromptTemplate" in request:
            t = request["ExecPromptTemplate"]
            if t["template"] == "EqNonComparativeLeader":
                prompt = f"{LEADER}\n{t['task']}\n{t['input']}\n{t['criteria']}"
            elif t["template"] == "EqNonComparativeValidator":
                prompt = (
                    f"{VALIDATOR} output={t['output']!r}\n"
                    f"{t['task']}\n{t['input']}\n{t['criteria']}"
                )
            else:
                raise AssertionError(f"unexpected template {t['template']}")
            vm.last_prompt = prompt
            response = vm._match_llm_mock(prompt)
            if response is None:
                raise wasi_mock.MockNotFoundError(f"No LLM mock for: {prompt[:120]}")
            if t["template"] == "EqNonComparativeValidator":
                assert response in ("true", "false"), response
                response = response == "true"
            return {"ok": response}
        return original(vm, request)

    monkeypatch.setattr(wasi_mock, "_handle_gl_call", handle)
    direct_vm.strict_mocks = True
    direct_vm.check_pickling = True
