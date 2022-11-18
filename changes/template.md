## {{ versiondata.version }} Chia blockchain {{ versiondata.date }}

{% for section, _ in sections.items() %}
{% for category, val in definitions.items() if category in sections[section]%}
### {{ definitions[category]['name'] }}

{% if definitions[category]['showcontent'] %}
{% for text, values in sections[section][category].items() %}
- {{ text }}
{% endfor %}
{% endif %}
{% endfor %}
{% endfor %}
