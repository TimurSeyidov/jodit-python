---
title: API Reference (Swagger)
description: Interactive OpenAPI reference of every connector action.
hide:
  - toc
---

# API Reference

The OpenAPI 3.1 document is generated from the Pydantic schemas of the actions (`make openapi`); a test checks that real answers match it. Download: [openapi.yaml](openapi.yaml) · [openapi.json](openapi.json).

Every action is shown as `/{action}`; `/?action={action}` is the same call. Actions that are documented as `GET` accept `POST` too (form or JSON body), which is required when `onlyPOST` is on.

!!! tip "Try it out"
    "Try it out" sends requests from this page to the server selected below (`http://localhost:8081/` by default), so a connector must be running there and accept cross-origin requests. Otherwise the browser reports *Failed to fetch*. For a local connector:

    ```bash
    CONFIG='{"allowCrossOrigin": true}' make run
    ```

<swagger-ui src="openapi.yaml"/>
