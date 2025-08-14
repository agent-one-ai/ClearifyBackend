from pydantic import BaseModel, EmailStr, validator

class Prompt(BaseModel):
    name: str
    prompt: str





