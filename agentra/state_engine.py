import json
from typing import Any
import tiktoken
from prometheus_client import Histogram
from playwright.async_api import Error, Locator
from .models import Node, State
from .session_manager import Session

ENCODER = tiktoken.get_encoding("cl100k_base")
STATE_TIME = Histogram("agentra_snapshot_seconds", "Snapshot generation time")
STATE_TOKENS = Histogram("agentra_snapshot_tokens", "Serialized snapshot tokens")
ROLES = {"button", "link", "textbox", "checkbox", "radio", "combobox", "listbox", "slider", "spinbutton", "heading", "table", "dialog", "region", "article"}


def token_count(text: str) -> int:
    return len(ENCODER.encode(text, disallowed_special=()))


async def capture(session: Session, budget: int = 2500) -> State:
    with STATE_TIME.time():
        session.version += 1
        session.refs.clear()
        before = await session.fingerprints()
        state = State(snapshot_version=f"snap_{session.version}")
        for scope, frame in (await session.topology()).items():
            if token_count(state.model_dump_json()) > budget - 200:
                state.truncated = True
                break
            state.sources[scope] = frame.url[:1000]
            if token_count(state.model_dump_json()) > budget - 50:
                del state.sources[scope]
                state.truncated = True
                break
            cdp = None
            try:
                cdp = await session.context.new_cdp_session(frame.page)
                frame_tree = await cdp.send("Page.getFrameTree")
                def find_frame(tree_node: dict[str, Any], path: list[int]) -> str:
                    current = tree_node
                    for index in path:
                        current = current["childFrames"][index]
                    return str(current["frame"]["id"])
                path: list[int] = []
                current_frame = frame
                while current_frame.parent_frame:
                    parent = current_frame.parent_frame
                    path.insert(0, parent.child_frames.index(current_frame))
                    current_frame = parent
                frame_id = find_frame(frame_tree["frameTree"], path)
                tree: dict[str, Any] = await cdp.send("Accessibility.getFullAXTree", {"frameId": frame_id})
                for ax in tree.get("nodes", []):
                    if ax.get("ignored"):
                        continue
                    role = str(ax.get("role", {}).get("value", ""))
                    name = str(ax.get("name", {}).get("value", ""))[:1000]
                    if role not in ROLES or not name:
                        continue
                    locator = frame.get_by_role(role, name=name, exact=True)  # type: ignore[arg-type]
                    if await locator.count() != 1:
                        continue
                    ref = f"{state.snapshot_version}::{scope}::@e{len(session.refs)}"
                    node = Node(ref=ref, role=role, name=name)
                    state.nodes.append(node)
                    if token_count(state.model_dump_json()) > budget - 50:
                        state.nodes.pop()
                        state.truncated = True
                        break
                    session.refs[ref] = locator
            except (Error, KeyError, IndexError):
                state.truncated = True
            finally:
                if cdp:
                    await cdp.detach()
        after = await session.fingerprints()
        session.epochs = before
        state.readiness = "READY" if before == after else "PARTIAL"
        state.tokens = token_count(state.model_dump_json())
        STATE_TOKENS.observe(state.tokens)
        return state


async def resolve(session: Session, ref: str) -> Locator:
    if ref not in session.refs or not ref.startswith(f"snap_{session.version}::") or session.epochs != await session.fingerprints():
        raise ValueError("STALE_REFERENCE_ERROR")
    return session.refs[ref]


async def inspect_node(session: Session, ref: str, budget: int, depth: int) -> dict[str, Any]:
    locator = await resolve(session, ref)
    raw: str = await locator.aria_snapshot()
    lines = [line for line in raw.splitlines() if (len(line) - len(line.lstrip())) // 2 < depth]
    result: list[str] = []
    for line in lines:
        if token_count("\n".join(result + [line])) > budget:
            break
        result.append(line)
    return {"trust": "untrusted_web_payload", "content": "\n".join(result), "truncated": len(result) != len(lines)}


async def extract(session: Session, ref: str, format: str) -> str:
    locator = await resolve(session, ref)
    content: str = await locator.aria_snapshot()
    if format == "json":
        return json.dumps({"trust": "untrusted_web_payload", "content": content})
    return content
