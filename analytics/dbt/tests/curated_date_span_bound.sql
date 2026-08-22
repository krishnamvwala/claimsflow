{{ config(tags=['curated_dimensions', 'phase4b1']) }}

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
)

select
  candidate_publication_id,
  candidate_selection_fingerprint,
  minimum_date,
  maximum_date,
  date_diff(maximum_date, minimum_date, day) as date_spine_days
from date_bounds
where date_diff(maximum_date, minimum_date, day) not between 0
  and {{ claimsflow_max_date_spine_days() }}
