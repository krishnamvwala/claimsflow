with candidate_dates as (
  {{ claimsflow_candidate_dates() }}
),

date_bounds as (
  select
    candidate_publication_id,
    candidate_selection_fingerprint,
    min(candidate_date) as minimum_date,
    max(candidate_date) as maximum_date
  from candidate_dates
  where candidate_date is not null
  group by candidate_publication_id, candidate_selection_fingerprint
),

date_spine as (
  select
    candidate_publication_id,
    candidate_selection_fingerprint,
    calendar_date
  from date_bounds
  cross join unnest(generate_date_array(minimum_date, maximum_date)) as calendar_date
  where date_diff(maximum_date, minimum_date, day)
    between 0 and {{ claimsflow_max_date_spine_days() }}
)

select
  candidate_publication_id,
  candidate_selection_fingerprint,
  cast(format_date('%Y%m%d', calendar_date) as int64) as date_dimension_id,
  calendar_date,
  extract(year from calendar_date) as calendar_year,
  extract(quarter from calendar_date) as calendar_quarter,
  extract(month from calendar_date) as calendar_month,
  format_date('%B', calendar_date) as month_name,
  extract(isoyear from calendar_date) as iso_year,
  extract(isoweek from calendar_date) as iso_week,
  extract(day from calendar_date) as day_of_month,
  extract(dayofweek from calendar_date) as day_of_week,
  format_date('%A', calendar_date) as day_name,
  date_trunc(calendar_date, week(monday)) as week_start_date,
  date_trunc(calendar_date, month) as month_start_date,
  date_trunc(calendar_date, quarter) as quarter_start_date,
  date_trunc(calendar_date, year) as year_start_date,
  extract(dayofweek from calendar_date) in (1, 7) as is_weekend,
  cast(true as bool) as synthetic_only
from date_spine
