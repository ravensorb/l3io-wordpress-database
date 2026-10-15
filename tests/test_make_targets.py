"""Make recipes whose failure modes leak something."""

from __future__ import annotations

from pathlib import Path

MAKEFILE = Path(__file__).resolve().parent.parent / "Makefile"


def recipe(target: str) -> str:
    lines = MAKEFILE.read_text(encoding="utf-8").splitlines()
    start = next(i for i, line in enumerate(lines) if line.startswith(f"{target}:"))
    body = []
    for line in lines[start + 1 :]:
        if not line.startswith("\t"):
            break
        body.append(line)
    assert body, f"{target} has no recipe"
    return "\n".join(body)


def test_an_interrupted_transfer_run_removes_its_server() -> None:
    """Ctrl-C must remove both containers, or a server is left holding the port.

    Under dash an EXIT trap does not run on a signal unless the signal is trapped
    too. And the shell runs no trap until its foreground child returns, while
    the ``docker run`` client catches Ctrl-C and keeps waiting on a container
    whose PID 1 ignores it. So the client runs in the background, the shell
    blocks in ``wait`` (which a trapped signal interrupts), and the EXIT trap
    removes the test container by name.
    """
    body = recipe("test-transfer")
    assert "trap 'exit 130' INT TERM" in body
    [exit_trap] = [line for line in body.splitlines() if line.rstrip(" ;\\").endswith("EXIT")]
    assert "-tests" in exit_trap, "the EXIT trap does not remove the test container"
    assert '--name "$$name-tests"' in body
    assert "wait $$!" in body, "a foreground docker run defers every trap until it returns"
