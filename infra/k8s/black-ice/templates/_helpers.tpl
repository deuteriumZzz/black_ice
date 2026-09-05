{{- define "black-ice.labels" -}}
app.kubernetes.io/part-of: black-ice
app.kubernetes.io/managed-by: {{ .Release.Service }}
{{- end -}}

{{- define "black-ice.componentLabels" -}}
{{ include "black-ice.labels" . }}
app.kubernetes.io/component: {{ .component }}
{{- end -}}

{{- define "black-ice.image" -}}
{{ .Values.image.registry }}/{{ .component }}:{{ .Values.image.tag }}
{{- end -}}

{{/*
Secret envFrom entry for DATABASE_URL/BLACK_ICE_API_KEYS. Vault mode (see
values.yaml's vault.* comment): those two names live only in Vault's KV
store, resolved at app startup by libs/black_ice_common/secrets.py — the pod
only needs VAULT_TOKEN, sourced from an externally-managed Secret this chart
does not create (vaultTokenSecretRef).
*/}}
{{- define "black-ice.secretsEnvFrom" -}}
{{- if .Values.vault.enabled -}}
- secretRef: { name: {{ .Values.vault.vaultTokenSecretRef }} }
{{- else -}}
- secretRef: { name: black-ice-secrets }
{{- end -}}
{{- end -}}
