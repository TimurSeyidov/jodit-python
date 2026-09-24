---
title: API Reference (Swagger)
description: Interactive OpenAPI reference of every connector action.
hide:
  - toc
---

# API Reference

The OpenAPI 3.1 document is generated from the Pydantic schemas of the
actions (`make openapi`); a test checks that real answers match it.
Download: [openapi.yaml](openapi.yaml) · [openapi.json](openapi.json).

Every action is shown as `/{action}`; `/?action={action}` is the same
call. Actions that are documented as `GET` accept `POST` too (form or
JSON body), which is required when `onlyPOST` is on.

<swagger-ui src="openapi.yaml"/>
