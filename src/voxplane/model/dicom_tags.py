"""Immutable metadata exchanged between the tag reader and the GUI thread."""

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class TagNode:
    node_id: str
    tag: str
    name: str
    keyword: str
    vr: str
    value: str
    children: tuple["TagNode", ...] = ()
    is_item: bool = False


@dataclass(frozen=True, slots=True)
class TagReadRequest:
    request_id: str
    tab_id: str
    instance_uid: str
    path: Path


@dataclass(frozen=True, slots=True)
class TagReadResult:
    request: TagReadRequest
    nodes: tuple[TagNode, ...] = ()
    error: str = ""
