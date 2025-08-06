from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.core.config import settings
from app.api import auth

# Create FastAPI app
app = FastAPI(
    title="CLEARIFY AI Backend",
    description="Backend API for CLEARIFY AI",
    version="1.0.0"
)

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


""" if settings.API_KEY:
    app.add_middleware(APIKeyMiddleware, api_key=settings.API_KEY)
 """
# Include routers
app.include_router(auth.router, prefix="/api/v1")

@app.get("/")
async def root():
    return {"message": "CLEARIFY AI Backend is running!"}

@app.get("/health")
async def health_check():
    return {"status": "healthy", "version": "1.0.0"}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=settings.PORT)