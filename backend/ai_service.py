import os
import json
import logging
from langchain_groq import ChatGroq
from langchain_core.prompts import PromptTemplate
from langchain_core.output_parsers import JsonOutputParser

log = logging.getLogger(__name__)
MODEL_NAME = "llama-3.1-8b-instant"


async def _request_recommendations(owner: str, name: str, base_recommendations: list[dict], api_key: str):
    llm = ChatGroq(model=MODEL_NAME, groq_api_key=api_key, temperature=0.2)

    prompt = PromptTemplate.from_template(
        """Ты — строгий техлид платформы SourceCraft. 
        Напиши общую сводку и улучши рекомендации для репозитория {owner}/{name}.

        Базовые рекомендации:
        {recommendations}

        Верни СТРОГО валидный JSON-объект с двумя ключами:
        1. "summary": строка (2-3 предложения об общем состоянии проекта, что хорошо, а что плохо).
        2. "recommendations": массив объектов (улучшенные базовые рекомендации с ключами: "category", "priority", "title", "problem", "why", "action", "impact").

        Отвечай только JSON-объектом, без лишнего текста.
        """
    )

    recs_json = json.dumps(base_recommendations, ensure_ascii=False)
    chain = prompt | llm | JsonOutputParser()

    return await chain.ainvoke({"owner": owner, "name": name, "recommendations": recs_json})


def _validate_response(response: object) -> dict:
    if not isinstance(response, dict) or not isinstance(response.get("summary"), str):
        raise ValueError("AI response must contain a text summary")
    recommendations = response.get("recommendations")
    if not isinstance(recommendations, list):
        raise ValueError("AI recommendations must be a list")
    fields = ("category", "priority", "title", "problem", "why", "action", "impact")
    for recommendation in recommendations:
        if not isinstance(recommendation, dict):
            raise ValueError("AI recommendation must be an object")
        if not all(isinstance(recommendation.get(field, ""), str) for field in fields):
            raise ValueError("AI recommendation fields must be text")
        if not (recommendation.get("title") or recommendation.get("action")):
            raise ValueError("AI recommendation must contain a title or action")
    return {"summary": response["summary"], "recommendations": recommendations, "model": MODEL_NAME}


async def generate_ai_recommendations_list(owner: str, name: str, base_recommendations: list[dict]) -> dict:
    """Use AI when available, otherwise return the rule engine result."""
    fallback = {"summary": "", "recommendations": base_recommendations, "model": None}
    api_key = os.getenv("GROQ_API_KEY")
    if not api_key:
        return fallback
    try:
        response = await _request_recommendations(owner, name, base_recommendations, api_key)
        return _validate_response(response)
    except Exception as exc:
        log.warning("AI recommendations unavailable: %s", type(exc).__name__)
        return fallback
