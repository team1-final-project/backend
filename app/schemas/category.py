from pydantic import BaseModel, ConfigDict


class SubCategoryResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str


class MainCategoryResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    subCategories: list[SubCategoryResponse]