import numpy as np
import pandas as pd

def map_severity_score(val):
    if pd.isna(val) or val == 'Unknown': return 50.0
    text = str(val).upper()
    if 'CRITICAL' in text or 'HIGH' in text: return 0.0
    if 'MEDIUM' in text: return 60.0
    if 'LOW' in text: return 80.0
    return 50.0

def map_status_score(val):
    if pd.isna(val) or val == 'Unknown': return 50.0
    text = str(val).upper()
    if 'RESOLVED' in text or 'CLOSED' in text: return 100.0
    if 'OPEN' in text: return 20.0
    return 50.0

def map_engine_score(val):
    if pd.isna(val) or val == 'Unknown': return 50.0
    return 100.0 if len(str(val)) > 0 else 50.0

def normalize_metric_safe(series, missing_val=-1.0, higher_is_better=True, neutral_score=50.0):
    scores = series.copy().astype(float)
    valid = scores != missing_val

    if not valid.any():
        return pd.Series(neutral_score, index=series.index)

    min_val = scores[valid].min()
    max_val = scores[valid].max()

    if max_val == min_val:
        scores.loc[valid] = 100.0 if higher_is_better else neutral_score
    else:
        if higher_is_better:
            scaled = ((scores[valid] - min_val) / (max_val - min_val)) * 100
        else:
            scaled = ((max_val - scores[valid]) / (max_val - min_val)) * 100
        scores.loc[valid] = np.clip(scaled, 0, 100)

    scores.loc[~valid] = neutral_score
    return scores

def aggregate_category_scores(df):
    categories = {
        'score_security': 'security.',
        'score_cicd': 'cicd.',
        'score_issues': 'issues.',
        'score_activity': 'activity.',
        'score_docs': 'documentation.',
        'score_health': 'code_health.'
    }
    df_agg = pd.DataFrame(index=df.index)
    for cat_score, prefix in categories.items():
        cols = [c for c in df.columns if c.startswith(prefix) and c.endswith('_score')]
        if cols:
            df_agg[cat_score] = df[cols].mean(axis=1).fillna(50.0)
        else:
            df_agg[cat_score] = 50.0
    return df_agg

# Версия методики: попадает в ответы API и в выгруженные отчёты
FORMULA_VERSION = "scoring-optuna-1.0"

# Веса подобраны Optuna, см. scoring/notebooks/optuna_and_check.ipynb
BEST_WEIGHTS = {
    'w_sec': 0.198, 'w_health': 0.298, 'w_issues': 0.191,
    'w_act': 0.108, 'w_doc': 0.100, 'w_cicd': 0.102,
}

# Соответствие внутренних ключей весов и категорий контракта API
WEIGHT_KEY_BY_CATEGORY = {
    'security': 'w_sec', 'code_health': 'w_health', 'issues': 'w_issues',
    'activity': 'w_act', 'documentation': 'w_doc', 'cicd': 'w_cicd',
}

CATEGORY_STATUS_COLUMN = {
    'security': 'collection.category_status.security',
    'code_health': 'collection.category_status.code_health',
    'issues': 'collection.category_status.issues',
    'activity': 'collection.category_status.activity',
    'documentation': 'collection.category_status.documentation',
    'cicd': 'collection.category_status.cicd',
}

SCORE_COLUMN_BY_CATEGORY = {
    'security': 'score_security', 'code_health': 'score_health', 'issues': 'score_issues',
    'activity': 'score_activity', 'documentation': 'score_docs', 'cicd': 'score_cicd',
}


def default_active_mask(df: pd.DataFrame) -> pd.DataFrame:
    """Какие категории участвуют в расчёте.

    Логика авторская и не менялась: из знаменателя исключаются только security и
    cicd, когда сборщик пометил их как unavailable. Остальные четыре категории
    всегда активны.
    """
    mask = pd.DataFrame(index=df.index)
    for category in WEIGHT_KEY_BY_CATEGORY:
        column = CATEGORY_STATUS_COLUMN[category]
        if category in ('security', 'cicd') and column in df.columns:
            mask[category] = (df[column].fillna('') != 'unavailable').astype(int)
        else:
            mask[category] = 1
    return mask


def compute_scores_frame(df: pd.DataFrame, active_mask: pd.DataFrame | None = None) -> pd.DataFrame:
    """Расчёт оценок сразу по всей выгрузке.

    Нормализация метрик идёт по min/max всего датасета, поэтому считать строки
    по одной нельзя — результат зависит от выборки.

    Возвращает датафрейм с оценками категорий (score_*), нормированными весами
    (weight_<категория>), долей покрытия данными (coverage) и итогом.
    """
    df_main = df.copy()

    bool_cols = [
        'documentation.has_readme', 'documentation.has_license', 'documentation.has_contributing',
        'documentation.has_code_of_conduct', 'documentation.has_changelog', 'documentation.has_docs_dir',
        'documentation.has_issue_templates', 'documentation.has_pr_template', 'cicd.has_ci_config',
        'cicd.has_test_stage', 'cicd.has_lint_or_security_stage', 'cicd.has_deploy_stage',
        'cicd.pipeline_history_available', 'cicd.branch_protection_enabled', 'security.appsec_available',
        'security.has_security_policy', 'activity.releases.uses_semver'
    ]

    heavy_log_cols = [
        'cicd.median_duration_seconds', 'security.oldest_open_defect_group_age_days',
        'activity.pull_requests.avg_merge_time_hours', 'activity.releases.median_interval_days',
        'issues.avg_time_to_first_response_hours', 'issues.avg_time_to_close_hours',
        'code_health.oldest_todo_age_days', 'documentation.readme_length_chars',
        'code_health.lines_of_code_estimate', 'code_health.largest_file_lines',
        'activity.commits_365d', 'activity.likes.value', 'activity.contributors_365d', 'issues.open_count'
    ]

    higher_is_better_cols = [
        'documentation.docs_file_count', 'documentation.readme_length_chars', 'cicd.declared_stage_count',
        'cicd.runs_30d', 'security.resolved_false_positive_total', 'activity.commits_30d', 'activity.commits_90d',
        'activity.commits_365d', 'activity.contributors_365d', 'activity.branch_count', 'activity.tag_count',
        'activity.pull_requests.merged_90d', 'activity.releases.count', 'activity.likes.value',
        'activity.likes.percentile', 'issues.closed_90d', 'code_health.file_count', 'code_health.lines_of_code_estimate'
    ]

    lower_is_better_cols = [
        'documentation.last_readme_change_at_days_ago', 'cicd.last_run_at_days_ago', 'cicd.median_duration_seconds',
        'security.open_defect_groups_total', 'security.oldest_open_defect_group_age_days', 'security.latest_scan_days_ago',
        'activity.last_commit_at_days_ago', 'activity.pull_requests.open', 'activity.pull_requests.stale_open_count',
        'activity.pull_requests.avg_merge_time_hours', 'activity.releases.median_interval_days',
        'activity.releases.last_release_at_days_ago', 'issues.open_count', 'issues.opened_90d',
        'issues.stale_open_count', 'issues.unanswered_open_count', 'issues.avg_time_to_first_response_hours',
        'issues.avg_time_to_close_hours', 'code_health.largest_file_lines', 'code_health.todo_count',
        'code_health.fixme_count', 'code_health.hack_count', 'code_health.todo_density_per_kloc',
        'code_health.oldest_todo_age_days'
    ]

    for col in heavy_log_cols:
        if col in df_main.columns:
            df_main[col] = df_main[col].astype(float)
            valid_mask = df_main[col] != -1.0
            df_main.loc[valid_mask, col] = np.log1p(df_main.loc[valid_mask, col])

    for col in bool_cols:
        if col in df_main.columns:
            df_main[col + '_score'] = df_main[col].astype(int) * 100

    if 'cicd.success_rate_30d' in df_main.columns:
        valid_sr = df_main['cicd.success_rate_30d'] != -1.0
        df_main['cicd.success_rate_30d_score'] = 50.0
        df_main.loc[valid_sr, 'cicd.success_rate_30d_score'] = df_main.loc[valid_sr, 'cicd.success_rate_30d'] * 100

    if 'activity.bus_factor_top1_share_365d' in df_main.columns:
        valid_bf = df_main['activity.bus_factor_top1_share_365d'] != -1.0
        df_main['activity.bus_factor_top1_share_365d_score'] = 50.0
        df_main.loc[valid_bf, 'activity.bus_factor_top1_share_365d_score'] = (1.0 - df_main.loc[valid_bf, 'activity.bus_factor_top1_share_365d']) * 100

    status_map = {'SUCCESS': 100, 'PASSED': 100, 'FAILED': 0, 'ERROR': 0}
    if 'cicd.last_run_status' in df_main.columns:
        df_main['cicd.last_run_status_score'] = df_main['cicd.last_run_status'].map(lambda x: status_map.get(x, 50))

    if 'documentation.license_type' in df_main.columns:
        df_main['documentation.license_type_score'] = df_main['documentation.license_type'].map(lambda x: 100 if x in ['BSD', 'MIT', 'Apache-2.0', 'GPL'] else 50)

    if 'security.defect_groups_by_severity' in df_main.columns:
        df_main['security.defect_groups_by_severity_score'] = df_main['security.defect_groups_by_severity'].apply(map_severity_score)
    if 'security.defect_groups_by_status' in df_main.columns:
        df_main['security.defect_groups_by_status_score'] = df_main['security.defect_groups_by_status'].apply(map_status_score)
    if 'security.defect_groups_by_engine_type' in df_main.columns:
        df_main['security.defect_groups_by_engine_type_score'] = df_main['security.defect_groups_by_engine_type'].apply(map_engine_score)

    for col in higher_is_better_cols:
        if col in df_main.columns:
            df_main[col + '_score'] = normalize_metric_safe(df_main[col], higher_is_better=True)

    for col in lower_is_better_cols:
        if col in df_main.columns:
            df_main[col + '_score'] = normalize_metric_safe(df_main[col], higher_is_better=False)

    df_categories = aggregate_category_scores(df_main)
    df_main = pd.concat([df_main, df_categories], axis=1)


    if active_mask is None:
        active_mask = default_active_mask(df_main)

    weights = pd.DataFrame(
        {cat: BEST_WEIGHTS[key] * active_mask[cat] for cat, key in WEIGHT_KEY_BY_CATEGORY.items()},
        index=df_main.index,
    )
    weight_sum = weights.sum(axis=1)
    norm_weights = weights.div(weight_sum.replace(0, pd.NA), axis=0)

    total = sum(
        df_main[SCORE_COLUMN_BY_CATEGORY[cat]] * norm_weights[cat].fillna(0)
        for cat in WEIGHT_KEY_BY_CATEGORY
    )
    total = total.where(weight_sum > 0)

    out = pd.DataFrame(index=df_main.index)
    for cat, column in SCORE_COLUMN_BY_CATEGORY.items():
        out[column] = df_main[column].round(1)
        out[f'weight_{cat}'] = norm_weights[cat].fillna(0).round(4)
        out[f'active_{cat}'] = active_mask[cat]
    out['coverage'] = (weight_sum / sum(BEST_WEIGHTS.values())).round(4)
    out['total_health_score'] = total.round(1)
    return out


def calculate_health_score(df: pd.DataFrame) -> dict:
    """Оценка одной строки. Обёртка над compute_scores_frame: формат ответа прежний."""
    scores = compute_scores_frame(df)
    first = scores.iloc[0]
    return {
        "total_health_score": first['total_health_score'],
        "categories": {
            "security": first['score_security'],
            "code_health": first['score_health'],
            "issues": first['score_issues'],
            "activity": first['score_activity'],
            "documentation": first['score_docs'],
            "cicd": first['score_cicd'],
        },
    }
