# Azure Container Apps template

Template status: locally authored; not cloud verified. The current account preflight did not establish protected zero-spend eligibility, so no resources were created.

The Bicep template allowlists exactly two resource types: one Consumption Container Apps environment and one container app. It creates no registry, storage, Log Analytics workspace, network, key vault, or custom domain. System-assigned identity has no data-plane grants. Feedback is disabled. Images must be pinned by digest; app tags carry the Git and model hashes.

`main.bicep` is a deployment template, not cost approval. Before running a mutation, complete and verify the cost gate using the deployment script and inspect its plan. Keep the Azure spending limit enabled and use only a preflight-approved region. The template has not been applied to a cloud subscription.
