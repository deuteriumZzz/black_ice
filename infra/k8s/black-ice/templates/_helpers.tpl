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
