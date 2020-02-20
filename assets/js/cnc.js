function add_list_item(widget_id, widget_name) {
    // construct a new input and attach it to the element identified by widget_id with name = widget_name
    event.preventDefault();
    let w = $('#' + widget_id);
    let new_input = $('<input type="text" class="form-control mt-3"/>');
    new_input.attr('name', widget_name);
    let current_value = w.find('input').last().val();
    let incremented = simple_increment(current_value);
    new_input.val(incremented);
    w.append(new_input);
}

function remove_list_item(widget_id, widget_name) {
    /*
        Allows removing a 'list' type item from the dynamic form. Finds the last element with the given widget_name
        and removes it.
     */
    event.preventDefault();
    let last_child = $('[name="' + widget_name + '"]').last();
    console.log('Removing last child of ' + widget_name);
    last_child.remove();
}


function simple_increment(val) {
    // Super simple function to attempt to do an increment of the given value
    if (val.split('.').length == 4) {
        console.log('looks like an IP');
        // this looks like an IP Address ?
        let ip_parts = val.split('.');
        let p0 = parseInt(ip_parts[0]);
        if (!isNaN(p0)) {
            // looks a bit like an IP
            let p3_parts = ip_parts[3].split('/');

            let last_octet = 0;

            if (p3_parts.length == 2) {
                last_octet = parseInt(p3_parts[0]);
                let netmask = parseInt(p3_parts[1]);
                if (isNaN(netmask) || (netmask > 32)) {
                    return val;
                }
                if (isNaN(last_octet)) {
                    return val;
                }
                if (last_octet === 255) {
                    last_octet = 0;
                } else {
                    last_octet += 1;
                }
                ip_parts[3] = last_octet;
                return ip_parts.join('.') + "/" + p3_parts[1];

            } else if (p3_parts.length < 2) {
                last_octet = parseInt(ip_parts[3]);
                if (!isNaN(last_octet)) {
                    // it's a valid int
                    if (last_octet === 255) {
                        ip_parts[3] = 0;
                    } else {
                        last_octet += 1;
                        ip_parts[3] = last_octet;
                    }
                    return ip_parts.join('.');
                }
            } else {
                let match = val.match(/\d+$/);
                if (match !== null) {
                    let match_int = parseInt(match[0]);
                    if (!isNaN(match_int)) {
                        return val.replace(match[0], match_int + 1)
                    }
                }
                return val;
            }
        }
    }
    console.log('no octets found');
    let match = val.match(/\d+$/);
    console.log(match);
    if (match !== null) {
        let match_int = parseInt(match[0]);
        if (!isNaN(match_int)) {
            return val.replace(match[0], match_int + 1)
        }
    }
    return val;
}

function increment_octet(octet) {
    if (octet >= 255) {
        return 0;
    } else {
        return octet += 1;
    }
}