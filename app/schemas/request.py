# app/schemas/request.py
#pydantic 是 FastAPI 默认常用的数据校验工具。检查json传入是否符合要求
from pydantic import BaseModel
# Optional[str] 的意思是：这个字段可以是字符串，也可以不传
from typing import Optional

class Text2SQLRequest(BaseModel):
    user_id: str
    question: str
    datasource_id: str
    session_id: Optional[str] = None