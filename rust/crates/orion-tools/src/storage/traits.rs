//! MemoryBackend trait for all storage backends.

use orion_core::{OrionError, RetrievalResult};
use serde_json::Value;

pub trait MemoryBackend: Send + Sync {
    fn backend_id(&self) -> &str;
    fn store(
        &self,
        content: &str,
        source: &str,
        metadata: Option<&Value>,
    ) -> Result<String, OrionError>;
    fn retrieve(
        &self,
        query: &str,
        top_k: usize,
    ) -> Result<Vec<RetrievalResult>, OrionError>;
    fn delete(&self, doc_id: &str) -> Result<bool, OrionError>;
    fn clear(&self) -> Result<(), OrionError>;
    fn count(&self) -> Result<usize, OrionError>;
}
