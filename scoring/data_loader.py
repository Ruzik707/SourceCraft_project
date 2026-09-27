import pandas as pd

def preprocess_data(raw_dict: dict) -> pd.DataFrame:
    """Подготовка одной записи. Обёртка над preprocess_frame."""
    return preprocess_frame(pd.DataFrame([raw_dict]))


def preprocess_frame(df: pd.DataFrame) -> pd.DataFrame:
    """Та же подготовка, но для всей выгрузки сразу: заполнение пропусков,
    приведение дат к «сколько дней назад» и категориальных значений."""
    df = df.copy()

    bool_cols = [
        'documentation.has_readme', 'documentation.has_license', 'documentation.has_contributing',
        'documentation.has_code_of_conduct', 'documentation.has_changelog', 'documentation.has_docs_dir',
        'documentation.has_issue_templates', 'documentation.has_pr_template', 'cicd.has_ci_config',
        'cicd.has_test_stage', 'cicd.has_lint_or_security_stage', 'cicd.has_deploy_stage',
        'cicd.pipeline_history_available', 'cicd.branch_protection_enabled', 'security.appsec_available',
        'security.has_security_policy', 'activity.releases.uses_semver'
    ]
    for col in bool_cols:
        if col in df.columns:
            df[col] = df[col].fillna(False)

    zero_cols = [
        'documentation.docs_file_count', 'documentation.readme_length_chars', 'cicd.declared_stage_count',
        'cicd.runs_30d', 'security.open_defect_groups_total', 'security.resolved_false_positive_total',
        'activity.commits_30d', 'activity.commits_90d', 'activity.commits_365d', 'activity.contributors_365d',
        'activity.branch_count', 'activity.tag_count', 'activity.pull_requests.open', 'activity.pull_requests.merged_90d',
        'activity.pull_requests.stale_open_count', 'activity.releases.count', 'activity.likes.value',
        'activity.likes.percentile', 'issues.open_count', 'issues.opened_90d', 'issues.closed_90d',
        'issues.stale_open_count', 'issues.unanswered_open_count', 'code_health.file_count',
        'code_health.lines_of_code_estimate', 'code_health.todo_count', 'code_health.fixme_count',
        'code_health.hack_count', 'code_health.largest_file_lines'
    ]
    for col in zero_cols:
        if col in df.columns:
            df[col] = df[col].fillna(0)

    time_and_rate_cols = [
        'cicd.median_duration_seconds', 'security.oldest_open_defect_group_age_days',
        'activity.pull_requests.avg_merge_time_hours', 'activity.releases.median_interval_days',
        'issues.avg_time_to_first_response_hours', 'issues.avg_time_to_close_hours',
        'code_health.oldest_todo_age_days', 'cicd.success_rate_30d', 'activity.bus_factor_top1_share_365d',
        'code_health.todo_density_per_kloc'
    ]
    for col in time_and_rate_cols:
        if col in df.columns:
            df[col] = df[col].fillna(-1.0)

    date_cols = [
        'documentation.last_readme_change_at', 'cicd.last_run_at', 'security.latest_scan',
        'activity.last_commit_at', 'activity.releases.last_release_at'
    ]

    if 'collection.collected_at' in df.columns:
        CURRENT_DATE = pd.to_datetime(df['collection.collected_at'], utc=True).fillna(pd.Timestamp.now(tz='UTC'))
    else:
        # Если нет, берем текущее системное время сервера
        CURRENT_DATE = pd.Timestamp.now(tz='UTC')

    for col in date_cols:
        if col in df.columns:
            df[col] = pd.to_datetime(df[col], errors='coerce', utc=True)
            df[f'{col}_days_ago'] = (CURRENT_DATE - df[col]).dt.days
            df[f'{col}_days_ago'] = df[f'{col}_days_ago'].fillna(-1.0)

    date_cols_days_ago = [f'{c}_days_ago' for c in date_cols]

    cat_cols = ['documentation.license_type', 'cicd.last_run_status', 'repo.primary_language']
    for col in cat_cols:
        if col in df.columns:
            df[col] = df[col].fillna('Unknown')

    return df