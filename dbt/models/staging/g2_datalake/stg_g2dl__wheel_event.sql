-- Wheel events counted once on event_id (the lake may carry duplicates).
select event_id, wheel_id, event_type, event_ts, _loaded_at
from {{ source('sim_g2_datalake', 'wheel_event') }}
qualify row_number() over (partition by event_id order by _loaded_at desc) = 1
