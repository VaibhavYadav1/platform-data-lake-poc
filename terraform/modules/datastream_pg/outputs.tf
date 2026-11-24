output "stream_id" {
  description = "Night-off (E8) pauses and resumes this stream."
  value       = google_datastream_stream.cdc.stream_id
}
