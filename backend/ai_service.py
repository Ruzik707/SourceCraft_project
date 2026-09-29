import os
import json
import logging
from langchain_groq import ChatGroq
from langchain_core.prompts import PromptTemplate
from langchain_core.output_parsers import JsonOutputParser

log = logging.getLogger(__name__)


async def generate_ai_recommendations_list(owner: str, name: str, base_recommendations: list[dict]) -> dict:
    """Отправляет факты в ИИ и возвращает JSON с summary и массивом рекомендаций."""
    api_key = os.getenv("GROQ_API_KEY")

    if not api_key:
        log.warning("GROQ_API_KEY не найден в .env")
        return {"summary": "", "recommendations": base_recommendations}

    llm = ChatGroq(model="llama-3.1-8b-instant", groq_api_key=api_key, temperature=0.2)

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

    try:
        return await chain.ainvoke({"owner": owner, "name": name, "recommendations": recs_json})
    except Exception as exc:
        log.error("Ошибка при генерации ИИ-рекомендаций: %s", exc)
        return {"summary": "Не удалось сгенерировать ИИ-сводку из-за сетевой ошибки.",
                "recommendations": base_recommendations}