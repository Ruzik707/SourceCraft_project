# Контракт API SourceCraft Repo Health

Описание реализованного API сервиса. Эти же формы описаны типами в
`frontend/src/api/types.ts` и машиночитаемо в [`openapi.yaml`](./openapi.yaml).

Фронтенд умеет работать и без бэкенда — на снимке данных в `frontend/public/mock`
(флаг `VITE_DATA_SOURCE=mock`). Это резервный режим для демонстрации, формы ответов
в нём те же.

Машиночитаемая версия: [`openapi.yaml`](./openapi.yaml).

- Базовый путь: `/api/v1`
- Формат: JSON, UTF-8
- Авторизация: `Authorization: Bearer <token>` (токен выдаётся после входа через Я ID)
- Все даты — строки ISO 8601 с таймзоной (`2026-09-20T10:59:15+00:00`)
- Все оценки — числа `0..100` **или `null`**, если данных нет. `null` ≠ 0.

## Ключевое соглашение: отсутствие данных

Любая категория может вернуть `score: null`. Это не ошибка и не плохой результат:

| `status` | Значение | Поведение фронта |
| --- | --- | --- |
| `ok` | данные собраны полностью | обычная оценка |
| `partial` | часть сигналов недоступна | оценка + доля покрытия `signal_coverage` |
| `no_data` | источник недоступен (например, AppSec отвечает 403) | категория исключается из Score, показывается причина |
| `not_applicable` | сущности нет (трекер не используется, кода почти нет) | категория исключается, показывается пояснение |

Поле `score.coverage` — доля веса методики, покрытая данными. Фронт показывает её рядом
с итоговой оценкой и использует как фильтр в рейтинге.

## Публичные эндпоинты

### `GET /repos`
Рейтинг открытых репозиториев.

Query-параметры:

| Параметр | Тип | Описание |
| --- | --- | --- |
| `query` | string | поиск по `full_path` и описанию |
| `language` | string | фильтр по основному языку |
| `sort` | `score` \| `likes` \| `activity` \| `name` | поле сортировки (по умолчанию `score`) |
| `order` | `asc` \| `desc` | направление (по умолчанию `desc`) |
| `page`, `page_size` | int | пагинация (по умолчанию 1 и 25) |
| `has_ci` | bool | только с найденной конфигурацией CI |
| `security_status` | `ok` \| `no_data` | наличие данных AppSec |
| `min_coverage` | float 0..1 | минимальная полнота данных (фронт по умолчанию шлёт `0.5`) |

Ответ: `{ items: RepoSummary[], total, page, page_size }`.

`RepoSummary`:

```jsonc
{
  "id": "0198c7be-d6b9-7a10-ada3-2781be8eaefa",  // repo.platform_id
  "full_path": "userver/userver",
  "owner": "userver",
  "name": "userver",
  "url": "https://sourcecraft.dev/userver/userver",
  "description": "Production-ready C++ Asynchronous Framework",
  "primary_language": "C++",
  "likes": 61.5,
  "last_activity_at": "2026-09-18T16:33:22+03:00",
  "analyzed_at": "2026-09-20T10:59:15+00:00",
  "total_score": 59.1,          // null, если ни одна категория не собрана
  "grade": "C",
  "coverage": 0.65,
  "categories": { "security": null, "code_health": 57.0, "activity": 100.0,
                  "documentation": 80.0, "cicd": 0.0, "issues": null },
  "no_data_categories": ["security"],
  "not_applicable_categories": ["issues"],
  "has_ci": false,
  "security_status": "no_data",
  "rank": 812,
  "rank_delta": 4               // опционально: изменение места с прошлого пересчёта
}
```

### `GET /repos/{owner}/{name}`
Полный отчёт (`RepoReport`) — то, что показывает страница анализа и что уходит в выгрузку.

```jsonc
{
  // ...все поля RepoSummary, кроме total_score/grade/coverage/categories/rank
  "visibility": "public",
  "default_branch": "develop",
  "likes_percentile": 2,
  "score": {
    "total": 59.1,
    "grade": "C",
    "coverage": 0.65,
    "formula_version": "1.0.0",
    "weights": { "security": 0.2, "code_health": 0.2, "activity": 0.15,
                 "documentation": 0.15, "cicd": 0.15, "issues": 0.15 }
  },
  "categories": [ CategoryScore, ... ],   // ровно шесть, в порядке методики
  "recommendations": [ Recommendation, ... ],
  "strengths": [ { "category": "activity", "text": "170 контрибьюторов за год" } ],
  "risks":     [ { "category": "cicd", "text": "Конфигурация CI не найдена" } ],
  "summary": "Repo Health Score 59 из 100 ...",   // 3–5 предложений для шапки и отчёта
  "collection": {
    "collected_at": "2026-09-20T10:59:15+00:00",
    "duration_ms": 75546,
    "collector_version": "0.1.0",
    "sources_used": { "git_clone": true, "platform_api": true,
                      "platform_cli": false, "appsec_api": true },
    "errors": [ { "category": "cicd", "source": "platform_api",
                  "code": "HTTP_ERROR", "message": "GET ... failed: 403 ..." } ]
  },
  "history": [ { "analyzed_at": "2026-09-20T10:59:15+00:00", "total": 59.1 } ]
}
```

`CategoryScore`:

```jsonc
{
  "key": "cicd",                     // security | code_health | activity | documentation | cicd | issues
  "title": "CI/CD",
  "score": 0.0,                      // null, если данных нет
  "status": "partial",
  "weight": 0.15,                    // номинальный вес в методике
  "effective_weight": 0.23,          // вес после исключения категорий без данных
  "signal_coverage": 0.5,            // доля сигналов категории, по которым были данные
  "summary": "0/100: конфигурация CI не найдена в репозитории",
  "strengths": [],
  "weaknesses": ["Конфигурация CI не найдена"],
  "no_data_reason": "История прогонов пайплайнов недоступна через API платформы.",
  "metrics": [
    {
      "key": "ci_config",
      "label": "Конфигурация CI",
      "value": false,                        // сырое значение
      "display": "не найдена",               // готовая строка для показа
      "status": "ok",
      "hint": "Без CI изменения не проверяются автоматически.",
      "source": "git_clone"
    }
  ]
}
```

Фронт ничего не досчитывает: `display` формирует бэкенд, иначе форматирование разъедется
между веб-страницей и выгруженным отчётом.

`Recommendation`:

```jsonc
{
  "id": "cicd.1",
  "category": "cicd",
  "priority": "high",            // critical | high | medium | low | info
  "title": "Настройте CI",
  "problem": "Конфигурация CI в репозитории не найдена.",
  "why": "Без CI регрессии обнаруживаются только вручную.",
  "action": "Добавьте .sourcecraft/ci.yaml со стадиями сборки, тестов и линта.",
  "evidence": [ { "label": "Конфигурация CI", "value": "не найдена",
                  "url": "https://sourcecraft.dev/userver/userver" } ],
  "expected_gain": 10.4,         // баллы итогового Score; 0 = не влияет напрямую
  "impact": "Разблокирует категорию CI/CD для начисления баллов."  // необязательно:
                                 // текстовая формулировка эффекта. Показывается,
                                 // когда expected_gain = 0
}
```

Сортировку фронт не меняет: показывает в том порядке, в котором прислал бэкенд
(ожидается: по приоритету, внутри приоритета — по `expected_gain`).

### `GET /languages`
`[{ "language": "Python", "count": 6432 }, ...]` — для фильтра рейтинга.

### `GET /stats`
```jsonc
{
  "repos_total": 27761, "repos_scored": 26480, "median_score": 48.2,
  "no_data_security": 27759, "with_ci": 5120,
  "last_run_at": "2026-09-22T03:00:00+00:00",
  "next_run_at": "2026-09-23T03:00:00+00:00",
  "schedule": "0 3 * * *"
}
```

### `GET /repos/{owner}/{name}/report.md` и `.pdf`
Необязательные эндпоинты. Фронт умеет формировать Markdown сам и печатать PDF из
браузера; если бэкенд отдаёт файлы, в меню выгрузки появляется пункт «PDF с сервера».
Заголовок: `Content-Disposition: attachment; filename="repo-health_owner_name_2026-09-20.pdf"`.

### `GET /badge/{owner}/{name}.svg`
SVG-бейдж для README (дополнительная возможность). Рекомендуется `Cache-Control: max-age=3600`.

## Авторизация через Я ID

1. `GET /auth/yandex/login?redirect_uri=<адрес фронта>` — бэкенд редиректит на страницу
   согласия Яндекс ID.
2. Пользователь возвращается на `redirect_uri`, который фронт передал в виде
   `https://<фронт>/auth/callback?next=<путь>`. Бэкенд добавляет к нему `?token=<jwt>`
   (или `error`/`error_description` при отказе).
3. Фронт сохраняет токен и вызывает `GET /me`.

Альтернатива: бэкенд ставит httpOnly-cookie сессии и возвращает `token` пустым — фронт
шлёт запросы с `credentials: 'include'`, так что оба варианта работают.

### `GET /me`
```jsonc
{ "id": "...", "login": "demo-user", "display_name": "Demo User",
  "email": "demo-user@example.com", "avatar_url": null, "provider": "yandex_id" }
```
`401` — фронт считает сессию истёкшей и показывает вход.

### `POST /me/sourcecraft-token`
Тело: `{ "token": "<личный токен доступа SourceCraft>" }`, ответ `204`.
Нужен, пока токен Я ID не даёт доступа к API платформы: сервис сохраняет токен в сессии
и ходит с ним за репозиториями пользователя. Удаляется вместе с сессией.

### `GET /me/repos`
Репозитории, доступные пользователю в SourceCraft: `RepoSummary` + поля
`role`, `visibility`, `last_analysis_at`. Приватные репозитории возвращаются только
владельцу и не попадают в публичный рейтинг.

Сервис берёт список с `GET https://api.sourcecraft.tech/me/repos`, передавая личный токен
доступа пользователя в заголовке `Authorization: Bearer`. Проверено на живом API.

Если токена нет или платформа не ответила, возвращается показательная подборка из витрины
с признаком `"demo": true` — интерфейс показывает плашку и предлагает добавить токен.

## Анализ по запросу

### `POST /analyses`
Тело: `{ "repo_full_path": "owner/name" }`. Ответ — `Analysis` со статусом `queued`.
Ошибки: `403` — нет прав на репозиторий, `429` — превышен лимит запусков.

### `GET /analyses/{id}`
```jsonc
{
  "id": "an_01J...", "repo_full_path": "userver/userver",
  "status": "running",            // queued | running | succeeded | failed
  "progress": 50,                 // 0..100
  "stages": [
    { "key": "clone",  "title": "Получение рабочей копии и Git-истории", "status": "done" },
    { "key": "appsec", "title": "Результаты AppSec SourceCraft", "status": "skipped",
      "detail": "AppSec вернул 403: категория Security останется без данных" }
  ],
  "started_at": "2026-09-22T17:40:00+00:00",
  "finished_at": null,
  "error": null,
  "report": null                  // RepoReport, когда status = succeeded
}
```

Фронт опрашивает эндпоинт раз в секунду, пока статус `queued`/`running`. Статусы стадий:
`pending | running | done | skipped | failed`; `skipped` используется, когда источник
недоступен — именно так на экране появляется честное «нет доступа» вместо ошибки.

## Ошибки

Единый формат: HTTP-код + тело `{ "code": "...", "message": "..." }`.
Фронт показывает свой текст для `0` (нет сети), `401`, `403`, `404`, `429`; для
остальных — `message` из ответа.
