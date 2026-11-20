-- Current state per key from the append-only change stream (A10).
{{ cdc_current_state(source('raw_g2', 'g2_device_locations'), ['device_id']) }}
