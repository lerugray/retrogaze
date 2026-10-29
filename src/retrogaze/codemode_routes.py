"""
Code mode API (``/code/*``): build, verify and bind code-drawn art.

Mounted at ``/code`` in api.py. Off unless ``RETROGAZE_CODE_MODE=1``; refused on the
public demo (``RETROGAZE_DEMO=1``) because it runs submitted JavaScript, which needs
OS-level isolation before it may run on a shared host (CODE-MODE-SPEC §3.7, §8 Q4).
Responses are built here, never through /generate's ``_STRIP_KEYS``: provenance is
always returned. Not part of the /v1 allowlist.
"""

from __future__ import annotations

import asyncio
import base64
import os
import tempfile
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from slowapi import Limiter
from slowapi.util import get_remote_address
from starlette.requests import Request

router = APIRouter()
limiter = Limiter(key_func=get_remote_address)

MAX_OUTPUT_BYTES = 64 * 1024 * 1024


def require_code_mode() -> None:
    if os.environ.get("RETROGAZE_CODE_MODE", "").strip() != "1":
        raise HTTPException(status_code=404, detail="Not Found")
    if os.environ.get("RETROGAZE_DEMO", "").strip() == "1":
        raise HTTPException(
            status_code=403,
            detail="Code mode runs submitted JavaScript and is not available on the public demo. "
                   "Run Retrogaze locally: python -m retrogaze.codemode build <art.px.js>",
        )


class BuildRequest(BaseModel):
    files: dict[str, str] = Field(..., description="Art sources: {relative name: text}. Only .px.js/.px.ts files.")
    entry: str = Field(..., description="The entry file name, one of the keys of `files`.")
    console: str = "nes"
    tier: str = Field("legal", description="'like' (palette and grid of the era) or 'legal' (real hardware limits)")
    author: str = Field("unknown", description="Who wrote the source: human, llm, mixed or unknown")
    include_outputs: bool = Field(True, description="Return every output file base64-encoded")


class BuildResponse(BaseModel):
    exit_code: int
    verdict: str
    report: dict
    provenance: dict | None = None
    manifest: dict | None = None
    outputs: dict[str, str] | None = None


class VerifyRequest(BaseModel):
    files: dict[str, str]
    manifest: dict
    outputs: dict[str, str] = Field(..., description="{relative path: base64 bytes} as returned by /code/build")


class VerifyResponse(BaseModel):
    exit_code: int
    messages: list[str]


@router.get("/binding", dependencies=[Depends(require_code_mode)])
@limiter.limit("60/minute")
async def code_binding(request: Request, console: str = "nes", tier: str = "legal") -> dict:
    from .codemode.binding import binding_for, check_supported, render_cheatsheet

    try:
        check_supported(console, tier)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    return {"console": console, "tier": tier, "cheatsheet": render_cheatsheet(console),
            "binding": binding_for(console, tier)}


@router.post("/build", response_model=BuildResponse, dependencies=[Depends(require_code_mode)])
@limiter.limit("30/minute")
async def code_build(request: Request, body: BuildRequest) -> BuildResponse:
    from .codemode.build import build

    result = await asyncio.to_thread(build, body.files, body.entry, console=body.console, tier=body.tier,
                                     author=body.author)
    if result.exit_code == 2:
        raise HTTPException(status_code=422, detail=result.report["errors"][0]["message"])
    outputs = None
    if body.include_outputs and result.outputs:
        if sum(len(v) for v in result.outputs.values()) > MAX_OUTPUT_BYTES:
            raise HTTPException(status_code=413, detail="outputs exceed the response size limit")
        outputs = {k: base64.b64encode(v).decode() for k, v in result.outputs.items()}
    return BuildResponse(
        exit_code=result.exit_code, verdict=result.verdict, report=result.report,
        provenance=(result.manifest or {}).get("provenance"), manifest=result.manifest, outputs=outputs,
    )


@router.post("/verify", response_model=VerifyResponse, dependencies=[Depends(require_code_mode)])
@limiter.limit("30/minute")
async def code_verify(request: Request, body: VerifyRequest) -> VerifyResponse:
    import json

    from .codemode.build import MANIFEST, verify
    from .codemode.runner import CodeModeError, validate_files

    try:
        validate_files(body.files, body.manifest.get("build", {}).get("entry", ""))
    except CodeModeError as e:
        raise HTTPException(status_code=422, detail=str(e))
    with tempfile.TemporaryDirectory() as tmp:
        src, out = Path(tmp) / "art", Path(tmp) / "out"
        for name, text in body.files.items():
            p = src / name
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(text, encoding="utf-8")
        for rel, b64 in body.outputs.items():
            p = (out / rel).resolve()
            if not p.is_relative_to(out.resolve()):
                raise HTTPException(status_code=422, detail=f"bad output path {rel!r}")
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_bytes(base64.b64decode(b64))
        man = dict(body.manifest)
        man["build"] = {**man.get("build", {}), "source_dir": "../art"}
        (out / MANIFEST).write_text(json.dumps(man), encoding="utf-8")
        code, msgs = await asyncio.to_thread(verify, out)
    return VerifyResponse(exit_code=code, messages=msgs)
