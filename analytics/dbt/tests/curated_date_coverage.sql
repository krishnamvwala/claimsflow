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

expected_dates as (
  select
    candidate_publication_id,
    candidate_selection_fingerprint,
    calendar_date
  from date_bounds
  cross join unnest(generate_date_array(minimum_date, maximum_date)) as calendar_date
  where date_diff(maximum_date, minimum_date, day)
    between 0 and {{ claimsflow_max_date_spine_days() }}
),

actual_dates as (
  select
    candidate_publication_id,
    candidate_selection_fingerprint,
    calendar_date
  from {{ ref('dim_date') }}
),

missing_dates as (
  select * from expected_dates
  except distinct
  select * from actual_dates
),

unexpected_dates as (
  select * from actual_dates
  except distinct
  select * from expected_dates
)

select 'missing_date' as failure_type, * from missing_dates
union all
select 'unexpected_date' as failure_type, * from unexpected_dates
{{ config(tags=['curated_dimensions', 'phase4b1']) }}
