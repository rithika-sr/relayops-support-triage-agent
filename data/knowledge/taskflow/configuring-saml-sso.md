---
slug: configuring-saml-sso
title: Configuring SAML single sign-on
kind: article
visibility: public
component: sso
product_versions: 2.4, 2.5
valid_from: 2026-07-01T00:00:00Z
---
# Configuring SAML single sign-on

SAML SSO is available on the Enterprise plan. An organization owner opens Settings, then Security, then Single sign-on.

## Steps

1. Copy the TaskFlow ACS URL and entity ID into your identity provider.
2. Upload the identity provider metadata XML.
3. Test with one user before enforcing SSO for everyone.

## Clock skew

TaskFlow accepts assertions up to 3 minutes outside the server clock. Larger skew causes the error SAML_CLOCK_SKEW.
