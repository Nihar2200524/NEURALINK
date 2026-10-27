import asyncio

from fastapi import APIRouter, Request
from fastapi.responses import PlainTextResponse

from app.core.exceptions import BridgeError
from app.models.request import BatchRequest, ExtractRequest, FetchRequest
from app.models.response import BridgeResponse
from app.services.formatter import Formatter

router = APIRouter(prefix="/v1")


def output(result: BridgeResponse, format: str, request: Request):
    request.state.result = result
    if format == "markdown":
        return PlainTextResponse(Formatter.markdown(result), media_type="text/markdown")
    return result


@router.post("/fetch", response_model=BridgeResponse)
async def fetch(options: FetchRequest, request: Request):
    return output(await request.app.state.manager.fetch(options), options.format, request)


@router.post("/extract", response_model=BridgeResponse)
async def extract(options: ExtractRequest, request: Request):
    return output(await request.app.state.manager.extract(options), options.format, request)


@router.post("/batch")
async def batch(options: BatchRequest, request: Request):
    slots = asyncio.Semaphore(request.app.state.manager.settings.concurrency)

    async def one(url):
        async with slots:
            try:
                item = FetchRequest(**options.model_dump(exclude={"urls"}), url=url)
                result = await request.app.state.manager.fetch(item)
                return {
                    "url": url,
                    "result": Formatter.markdown(result)
                    if options.format == "markdown"
                    else result.model_dump(),
                }
            except BridgeError as exc:
                return {"url": url, **exc.payload()}

    return {"results": await asyncio.gather(*(one(url) for url in options.urls))}
