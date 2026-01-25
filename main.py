"""
ObradorIA Agent - Sistema inteligente de geração de orçamentos
Entry point da aplicação
"""

import uvicorn
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app import __version__
from app.config import get_settings
from app.api.routes import router
from app.llm import close_all_providers
from app.services.vector_search import close_vector_search_service
from app.services.spring_client import close_spring_client


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Gerencia ciclo de vida da aplicação"""
    # Startup
    settings = get_settings()
    print(f"""
╔═══════════════════════════════════════════════════════════════╗
║                     ObradorIA Agent v{__version__}                    ║
╠═══════════════════════════════════════════════════════════════╣
║  Sistema inteligente de geração de orçamentos                 ║
╠═══════════════════════════════════════════════════════════════╣
║  Server: http://{settings.api_host}:{settings.api_port}                                  ║
║  Docs:   http://{settings.api_host}:{settings.api_port}/docs                             ║
╚═══════════════════════════════════════════════════════════════╝
    """)

    yield

    # Shutdown
    print("\nEncerrando conexões...")
    await close_all_providers()
    await close_vector_search_service()
    await close_spring_client()
    print("Conexões encerradas.")


# Criar aplicação FastAPI
app = FastAPI(
    title="ObradorIA Agent",
    description="Sistema inteligente de geração de orçamentos de construção civil",
    version=__version__,
    lifespan=lifespan
)

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:4200",  # Angular
        "http://localhost:8891",  # Spring Boot
        "http://localhost:3000",  # React
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Registrar rotas
app.include_router(router, prefix="/api")


@app.get("/")
async def root():
    """Redireciona para documentação"""
    return {"message": "ObradorIA Agent", "docs": "/docs"}


def main():
    """Entry point"""
    settings = get_settings()
    uvicorn.run(
        "main:app",
        host=settings.api_host,
        port=settings.api_port,
        reload=True
    )


if __name__ == "__main__":
    main()
