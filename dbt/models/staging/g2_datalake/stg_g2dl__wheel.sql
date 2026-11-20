select wheel_id, g2_store_id, cart_id, installed_at, status
from {{ source('sim_g2_datalake', 'wheel') }}
