# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

"""
Shell completion script generator for the appinfra CLI.

Generates completion scripts for bash and zsh shells.
"""

from typing import Any

from ...app.tools import Tool, ToolConfig
from ...app.tracing.traceable import Traceable

BASH_COMPLETION_TEMPLATE = """
# appinfra bash completion
# Add to ~/.bashrc:
#   eval "$(appinfra completion bash)"

_appinfra_completions() {
    local cur="${COMP_WORDS[COMP_CWORD]}"
    local prev="${COMP_WORDS[COMP_CWORD-1]}"

    # Main commands
    local commands="scaffold cq code-quality config cfg c docs d doctor dr init completion"

    case "$prev" in
        appinfra)
            COMPREPLY=($(compgen -W "$commands" -- "$cur"))
            return 0
            ;;
        scaffold)
            if [[ "$cur" == -* ]]; then
                COMPREPLY=($(compgen -W "--path --with-db --with-server --with-logging-db --makefile-style" -- "$cur"))
            fi
            return 0
            ;;
        cq|code-quality)
            COMPREPLY=($(compgen -W "cf check-funcs" -- "$cur"))
            return 0
            ;;
        config|cfg|c)
            if [[ "$cur" == -* ]]; then
                COMPREPLY=($(compgen -W "--format -f --no-env --section -s" -- "$cur"))
            else
                COMPREPLY=($(compgen -f -- "$cur"))
            fi
            return 0
            ;;
        docs|d)
            COMPREPLY=($(compgen -W "list show search" -- "$cur"))
            return 0
            ;;
        doctor|dr)
            if [[ "$cur" == -* ]]; then
                COMPREPLY=($(compgen -W "--pkg-name --project-root --json" -- "$cur"))
            fi
            return 0
            ;;
        init)
            if [[ "$cur" == -* ]]; then
                COMPREPLY=($(compgen -W "--pkg-name --strict --no-strict --output -o --force -f" -- "$cur"))
            fi
            return 0
            ;;
        completion)
            COMPREPLY=($(compgen -W "bash zsh" -- "$cur"))
            return 0
            ;;
        --format|-f)
            COMPREPLY=($(compgen -W "yaml json flat" -- "$cur"))
            return 0
            ;;
        --makefile-style)
            COMPREPLY=($(compgen -W "standalone framework" -- "$cur"))
            return 0
            ;;
    esac

    # Default to file completion
    COMPREPLY=($(compgen -f -- "$cur"))
}

complete -F _appinfra_completions appinfra
"""

ZSH_COMPLETION_TEMPLATE = """#compdef appinfra
# appinfra zsh completion
# Add to ~/.zshrc:
#   eval "$(appinfra completion zsh)"

_appinfra() {
    local -a commands
    commands=(
        'scaffold:Generate project scaffolding'
        'cq:Code quality checks'
        'code-quality:Code quality checks'
        'config:Display resolved configuration'
        'cfg:Display resolved configuration'
        'c:Display resolved configuration'
        'docs:Browse documentation'
        'd:Browse documentation'
        'doctor:Check project health'
        'dr:Check project health'
        'init:Initialize project configuration'
        'completion:Generate shell completion scripts'
    )

    local -a scaffold_options
    scaffold_options=(
        '--path[Path for project creation]:directory:_files -/'
        '--with-db[Include database configuration]'
        '--with-server[Include HTTP server configuration]'
        '--with-logging-db[Include database logging handler]'
        '--makefile-style[Makefile style]:style:(standalone framework)'
    )

    local -a config_options
    config_options=(
        '--format[Output format]:format:(yaml json flat)'
        '-f[Output format]:format:(yaml json flat)'
        '--no-env[Disable environment variable overrides]'
        '--section[Show specific section]:section:'
        '-s[Show specific section]:section:'
    )

    local -a doctor_options
    doctor_options=(
        '--pkg-name[Package name to validate]:name:'
        '--project-root[Project root directory]:directory:_files -/'
        '--json[Output results as JSON]'
    )

    local -a init_options
    init_options=(
        '--pkg-name[Package name]:name:'
        '--strict[Enable strict code quality mode]'
        '--no-strict[Disable strict code quality mode]'
        '--output[Output file path]:file:_files'
        '-o[Output file path]:file:_files'
        '--force[Overwrite existing file]'
        '-f[Overwrite existing file]'
    )

    _arguments -C \\
        '1:command:->command' \\
        '*::arg:->args'

    case "$state" in
        command)
            _describe -t commands 'appinfra commands' commands
            ;;
        args)
            case "$words[1]" in
                scaffold)
                    _arguments $scaffold_options \\
                        '1:project_name:'
                    ;;
                config|cfg|c)
                    _arguments $config_options \\
                        '1:config_file:_files -g "*.yaml *.yml"'
                    ;;
                cq|code-quality)
                    local -a subcommands
                    subcommands=('cf:Check function sizes' 'check-funcs:Check function sizes')
                    _describe -t subcommands 'code-quality subcommands' subcommands
                    ;;
                docs|d)
                    local -a subcommands
                    subcommands=('list:List documentation' 'show:Show documentation' 'search:Search documentation')
                    _describe -t subcommands 'docs subcommands' subcommands
                    ;;
                doctor|dr)
                    _arguments $doctor_options
                    ;;
                init)
                    _arguments $init_options
                    ;;
                completion)
                    _values 'shell' 'bash' 'zsh'
                    ;;
            esac
            ;;
    esac
}

_appinfra
"""


class CompletionTool(Tool):
    """
    Generate shell completion scripts for appinfra CLI.

    Supports bash and zsh shells with installation instructions.
    """

    def __init__(self, parent: Traceable | None = None):
        """Initialize the completion tool."""
        config = ToolConfig(
            name="completion",
            help_text="Generate shell completion scripts",
            description=(
                "Generate shell completion scripts for bash or zsh. "
                "Output the script to stdout for eval or save to a file."
            ),
        )
        super().__init__(parent, config)

    def add_args(self, parser: Any) -> None:
        """Add command-line arguments."""
        parser.add_argument(
            "shell",
            choices=["bash", "zsh"],
            help="Shell type (bash or zsh)",
        )
        parser.add_argument(
            "--install",
            action="store_true",
            help="Show installation instructions instead of script",
        )

    def run(self, **kwargs: Any) -> int:
        """Generate completion script."""
        shell = getattr(self.args, "shell", "bash")
        show_install = getattr(self.args, "install", False)

        if show_install:
            self._show_install_instructions(shell)
        else:
            self._output_completion_script(shell)

        return 0

    def _output_completion_script(self, shell: str) -> None:
        """Output the completion script to stdout."""
        if shell == "bash":
            print(BASH_COMPLETION_TEMPLATE.strip())
        else:
            print(ZSH_COMPLETION_TEMPLATE.strip())

    def _show_install_instructions(self, shell: str) -> None:
        """Show installation instructions."""
        if shell == "bash":
            print("# Bash completion installation")
            print("#")
            print("# Option 1: Add to ~/.bashrc (loads on every shell)")
            print("#   echo 'eval \"$(appinfra completion bash)\"' >> ~/.bashrc")
            print("#")
            print("# Option 2: Save to completion directory")
            print("#   sudo appinfra completion bash > /etc/bash_completion.d/appinfra")
            print("#   # or for user-local installation:")
            print("#   mkdir -p ~/.local/share/bash-completion/completions")
            print(
                "#   appinfra completion bash > "
                "~/.local/share/bash-completion/completions/appinfra"
            )
        else:
            print("# Zsh completion installation")
            print("#")
            print("# Option 1: Add to ~/.zshrc (loads on every shell)")
            print("#   echo 'eval \"$(appinfra completion zsh)\"' >> ~/.zshrc")
            print("#")
            print("# Option 2: Save to fpath directory")
            print("#   mkdir -p ~/.zsh/completions")
            print("#   appinfra completion zsh > ~/.zsh/completions/_appinfra")
            print("#   # Add to ~/.zshrc before compinit:")
            print("#   fpath=(~/.zsh/completions $fpath)")
            print("#   autoload -Uz compinit && compinit")
