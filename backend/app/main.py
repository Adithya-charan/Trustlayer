import logging

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api.extra import router as extra_router
from app.api.routes import router
from app.core.config import get_settings

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
log = logging.getLogger("trustlayer")

app = FastAPI(title="TrustLayer", version="0.1.0", docs_url="/api/docs", openapi_url="/api/openapi.json")
app.add_middleware(
    CORSMiddleware,
    allow_origins=get_settings().cors_list,
    allow_methods=["GET", "POST", "PATCH", "DELETE"],
    allow_headers=["Authorization", "Content-Type", "X-TrustLayer-Automation-Key", "Idempotency-Key"],
)
app.include_router(router)
app.include_router(extra_router)


@app.exception_handler(RequestValidationError)
async def validation_handler(_: Request, exc: RequestValidationError):
    # Field names and messages only; never echo submitted values.
    errs = [{"field": ".".join(str(p) for p in e["loc"][1:]), "message": e["msg"]} for e in exc.errors()]
    return JSONResponse(status_code=422, content={"detail": {"message": "Invalid request", "errors": errs}})


@app.exception_handler(Exception)
async def unhandled(_: Request, exc: Exception):
    log.error("unhandled error: %s", type(exc).__name__)  # no stack trace / secrets to client
    return JSONResponse(status_code=500, content={"detail": "Internal error"})
