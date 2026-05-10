from fastapi import APIRouter

from apps.api.routers import (
    analytics,
    auth,
    campaigns,
    circuit_breakers,
    contacts,
    domains,
    health,
    imports,
    lists,
    ops,
    segments,
    sender_profiles,
    suppression,
    templates,
    users,
)

api_router = APIRouter()
api_router.include_router(health.router)
api_router.include_router(auth.router)
api_router.include_router(users.router)
api_router.include_router(campaigns.router)
api_router.include_router(analytics.router)
api_router.include_router(circuit_breakers.router)
api_router.include_router(domains.router)
api_router.include_router(ops.router)
api_router.include_router(sender_profiles.router)
api_router.include_router(imports.router)
api_router.include_router(contacts.router)
api_router.include_router(lists.router)
api_router.include_router(templates.router)
api_router.include_router(segments.router)
api_router.include_router(suppression.router)
