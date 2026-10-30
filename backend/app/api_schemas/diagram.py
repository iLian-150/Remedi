"""结构化教学图形的 API schema。模型只能返回这些白名单图元。"""
from typing import Annotated, Literal, Optional, Union

from pydantic import BaseModel, ConfigDict, Field, FiniteFloat, model_validator


class _DiagramModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class DiagramBounds(_DiagramModel):
    x_min: FiniteFloat = Field(ge=-1000, le=1000)
    x_max: FiniteFloat = Field(ge=-1000, le=1000)
    y_min: FiniteFloat = Field(ge=-1000, le=1000)
    y_max: FiniteFloat = Field(ge=-1000, le=1000)

    @model_validator(mode="after")
    def check_ranges(self):
        if self.x_max <= self.x_min or self.y_max <= self.y_min:
            raise ValueError("坐标范围必须递增")
        if self.x_max - self.x_min < 0.2 or self.y_max - self.y_min < 0.2:
            raise ValueError("坐标范围太窄")
        if self.x_max - self.x_min > 2000 or self.y_max - self.y_min > 2000:
            raise ValueError("坐标范围过大")
        return self


class DiagramPoint(_DiagramModel):
    x: FiniteFloat = Field(ge=-1000, le=1000)
    y: FiniteFloat = Field(ge=-1000, le=1000)


DiagramColor = Literal["blue", "red", "green", "amber", "gray"]


class PointElement(_DiagramModel):
    type: Literal["point"]
    x: FiniteFloat = Field(ge=-1000, le=1000)
    y: FiniteFloat = Field(ge=-1000, le=1000)
    label: Optional[str] = Field(default=None, max_length=32)
    color: DiagramColor = "blue"


class SegmentElement(_DiagramModel):
    type: Literal["segment", "line"]
    start: DiagramPoint
    end: DiagramPoint
    label: Optional[str] = Field(default=None, max_length=32)
    color: DiagramColor = "blue"


class CircleElement(_DiagramModel):
    type: Literal["circle"]
    cx: FiniteFloat = Field(ge=-1000, le=1000)
    cy: FiniteFloat = Field(ge=-1000, le=1000)
    radius: FiniteFloat = Field(gt=0, le=2000)
    label: Optional[str] = Field(default=None, max_length=32)
    color: DiagramColor = "blue"


class PathElement(_DiagramModel):
    type: Literal["polyline", "polygon"]
    points: list[DiagramPoint] = Field(min_length=2, max_length=80)
    label: Optional[str] = Field(default=None, max_length=32)
    color: DiagramColor = "blue"


class QuadraticElement(_DiagramModel):
    type: Literal["quadratic"]
    a: FiniteFloat = Field(ge=-1000, le=1000)
    b: FiniteFloat = Field(ge=-1000, le=1000)
    c: FiniteFloat = Field(ge=-1000, le=1000)
    x_min: Optional[FiniteFloat] = Field(default=None, ge=-1000, le=1000)
    x_max: Optional[FiniteFloat] = Field(default=None, ge=-1000, le=1000)
    label: Optional[str] = Field(default=None, max_length=48)
    color: DiagramColor = "blue"

    @model_validator(mode="after")
    def check_domain(self):
        if self.x_min is not None and self.x_max is not None and self.x_max <= self.x_min:
            raise ValueError("抛物线定义域必须递增")
        return self


class TextElement(_DiagramModel):
    type: Literal["text"]
    x: FiniteFloat = Field(ge=-1000, le=1000)
    y: FiniteFloat = Field(ge=-1000, le=1000)
    text: str = Field(min_length=1, max_length=80)
    color: DiagramColor = "gray"


DiagramElement = Annotated[
    Union[PointElement, SegmentElement, CircleElement, PathElement, QuadraticElement, TextElement],
    Field(discriminator="type"),
]


class FigureSpec(_DiagramModel):
    version: Literal[1] = 1
    kind: Literal["coordinate", "geometry"] = "coordinate"
    bounds: DiagramBounds
    axes: bool = True
    grid: bool = True
    x_label: Optional[str] = Field(default="x", max_length=8)
    y_label: Optional[str] = Field(default="y", max_length=8)
    elements: list[DiagramElement] = Field(min_length=1, max_length=40)

    @model_validator(mode="after")
    def check_quadratic_domains(self):
        for element in self.elements:
            if isinstance(element, QuadraticElement):
                x_min = max(self.bounds.x_min, element.x_min if element.x_min is not None else self.bounds.x_min)
                x_max = min(self.bounds.x_max, element.x_max if element.x_max is not None else self.bounds.x_max)
                if x_max < x_min:
                    raise ValueError("抛物线定义域不在图形坐标范围内")
        return self


class FigureGenerateIn(_DiagramModel):
    subject: str = Field(
        pattern="^(math|english|english_exercise|physics|chemistry|biology|chinese|history|geography|politics|computer_science|art|music|pe|other)$",
    )
    question_text: str = Field(min_length=1, max_length=12000)


class FigureGenerateOut(_DiagramModel):
    figure: Optional[FigureSpec] = None
    message: str = Field(default="", max_length=120)
