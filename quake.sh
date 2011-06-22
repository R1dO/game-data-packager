#! /bin/sh

# quake.sh - launcher script for quake 1

data_location=/usr/share/games/quake
engine_path=/usr/games/quakespasm
no_data_msg="Missing data; see /usr/share/doc/quake/README.Debian"

main() {
    while [ $# -gt 0 ]; do
        case "$1" in
            -h|--help)
                show_help
                exit 2
                ;;
            -v|--version)
                show_version
                exit 2
                ;;
            *)
                break
                ;;
        esac

        shift
    done

    if ! [ -f "${data_location}/id1/pak0.pak" ]; then
        exec "$data_location"/need-data.sh "$no_data_msg"
    fi
    
    exec ${engine_path} -basedir ${data_location} "$@"
}

show_help() {
    echo "Usage: quake [-h|--help] [-v|--version] [ARG1] [ARG2] ..."
    echo "Launch Quake."
    echo
    echo "This script supports these options:"
    echo "  -h, --help       show this help information"
    echo "  -v, --version    show version information"
    echo
    echo "Any further arguments will be passed directly to the Quake engine."
}

show_version() {
    echo "Debian Quake 1 wrapper script"
    echo "Please consult your apt database for the version number of this script."
    echo "Looking for data at: '$data_location'"
    echo "Using engine: '$engine_path'"
}

main "$@"

