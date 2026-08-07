"""Camada de API (interface adapters): adapta a aplicação para HTTP/JSON.

É a única camada que conhece FastAPI/Pydantic. Depende da aplicação; a aplicação
NÃO depende dela (regra de dependência da Clean Architecture).
"""
