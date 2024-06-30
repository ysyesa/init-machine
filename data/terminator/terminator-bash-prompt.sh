# Custom Bash prompt for Terminator
if [ "$PS1" ]; then
  PROMPT_COMMAND='printf "\033]0;Hello, %s! [%s]\007" "${USER}" "${PWD}"'
  PS1="\[\e[${PROMPT_COLOR:-32}m\][\u@\h]\[\e[0m\]$ "
fi
