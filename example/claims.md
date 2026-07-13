# Claims about horror-shorts-pipeline
# Some of these are true. Some are the kind of thing an agent writes when it is
# being helpful rather than correct. claimcheck does not know which is which.

- The pipeline stores job state in a SQLite database
- Jobs move through a state machine with named states like scripted and posted
- Stages are idempotent, so re-running a completed stage is a no-op
- The pipeline uses a Postgres database for job state
- Video assembly is done with FFmpeg
- The project includes a RAG pipeline over a vector store for script retrieval
- Uploads to YouTube are scheduled rather than immediate
- Every LLM call is retried with exponential backoff and a circuit breaker
