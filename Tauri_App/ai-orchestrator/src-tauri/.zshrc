export OPENSSL_ROOT_DIR=/opt/homebrew/opt/openssl@3

# Added by LM Studio CLI (lms)
export PATH="$PATH:/Users/tvidk/.lmstudio/bin"
export PATH="$HOME/.pyenv/bin:$PATH"
eval "$(pyenv init --path)"
eval "$(pyenv virtualenv-init -)"
export PATH="$HOME/.pyenv/bin:$PATH"
eval "$(pyenv init --path)"
eval "$(pyenv virtualenv-init -)"
export PATH="$HOME/.pyenv/bin:$PATH"
eval "$(pyenv init --path)"
eval "$(pyenv init -)"
eval "$(pyenv virtualenv-init -)"


## FOR GHOSTTY
# Use exa instead of ls
alias ls="exa --icons --long --git"
# Use bat instead of cat
alias cat="bat --style=plain --paging=never"
# Neofetch on terminal start
neofetch

# -------------------------------
# Path setup (Homebrew)
# -------------------------------
export PATH="/usr/local/bin:/opt/homebrew/bin:$PATH"

# -------------------------------
# Starship prompt
# -------------------------------
eval "$(starship init zsh)"

# -------------------------------
# Zsh plugins
# -------------------------------
source /opt/homebrew/share/zsh-syntax-highlighting/zsh-syntax-highlighting.zsh
source /opt/homebrew/share/zsh-autosuggestions/zsh-autosuggestions.zsh

# -------------------------------
# Aliases
# -------------------------------
# Modern ls replacement with icons, git info
alias ls="eza --icons --long --git --group-directories-first"

# Bat for cat replacement with syntax highlighting
alias cat="bat"

# FZF default command
export FZF_DEFAULT_COMMAND='rg --files --hidden --follow -g "!{.git,node_modules}/*"'

# Ghostty (if you want to start a terminal server)
# ghostty start  # uncomment to auto-start

# Neofetch for system info
alias fetch="neofetch"

# Ripgrep shortcut
alias rg="rg --hidden --glob '!.git/*'"

# Clear screen alias
alias cls="clear"

# Commit to GitHub for FALCON Repository
git_push_falcon() {
    git add .
    git commit -m "$1"
    git push origin main
}

# -------------------------------
# Options
# -------------------------------
# Case-insensitive globbing
setopt nocaseglob

# Correct minor spelling errors in commands
setopt correct

# Auto cd into directories by typing name
setopt auto_cd

export MUJOCO_GL=glfw
export PATH="$HOME/.cargo/bin:$PATH"
