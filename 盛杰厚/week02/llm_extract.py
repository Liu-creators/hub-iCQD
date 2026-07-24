import json
from openai import OpenAI
from pydantic import BaseModel, Field

llm = OpenAI(
    api_key="sk-0e7927087ebe4069bed4e93d5d7d5744",
    base_url="https://api.deepseek.com",
)

## jsonModel Method
class Entity(BaseModel):
    """提取实体以及实体之间的关系"""
    person: str = Field(description="实体1")
    relationShip: str = Field(description="两者的关系")
    targetPerson: str = Field(description="实体2")



def getToolsDict(entity) -> dict:
    schema = entity.model_json_schema()
    data = {
            "type": "function",
            "function": {
                "name": schema.get("title", ""),
                "description": schema.get("description", ""),
                "parameters": {
                    "type": "object",
                    "properties": schema.get("properties"),
                    "required": schema.get("required"),
                },
            },
        }
    return data

TOOLS = [
    getToolsDict(Entity)
]


response = llm.chat.completions.create(
    model="deepseek-v4-flash",
    messages=[
         {
            "role": "system", "content": "你是一个实体关系提取专家。"
         },
        {
            "role": "user", "content": "小明喜欢小姚，但是小姚喜欢小王"
        }
    ],
    tools=TOOLS,
    temperature=0.0,
)

print(f"response {response}")

tool_calls = response.choices[0].message.tool_calls

if tool_calls:
    arguments = tool_calls[0].function.arguments
    print(f'argument {arguments}')
    model = Entity.model_validate_json(arguments)
    print("实体1", model.person)
    print("关系", model.relationShip)
    print("实体2", model.targetPerson)
else:
    print('ERROR', response.choices[0].message)



