# SPDX-License-Identifier: GPL-2.0

'''
Library module for handling Linux kernel's trace system and the user-space
tools.
'''

class Trace:
    timestamp = None
    proc = None
    event = None
    trace_fields = None

def parse_trace_line(line, tracer):
    '''
    Input should be output from 'perf script', 'perf trace
    --libtraceevent_print', 'trace-cmd report' or 'trace-cmd stream'.
    '''
    fields = line.split()
    if tracer == 'perf':
        #   3128.371 kdamond.0/764 damon:damon_aggregated(trace fields)
        timestamp, proc = fields[:2]
        event_first_trace_fields = fields[2].split('(')
        event = event_first_trace_fields[0]
        first_trace_field = '('.join(event_first_trace_fields[1:])
        remaining_trace_fields = fields[3:]
        if len(remaining_trace_fields) > 0:
            remaining_trace_fields[-1] = remaining_trace_fields[-1][:-1]
        trace_fields = [first_trace_field] + remaining_trace_fields
    elif tracer == 'trace-cmd':
        # <...>-764   [001] .....  1394.412830: damon_region_aggregated: trace fields
        proc = fields[0]
        timestamp = fields[3][:-1]
        event = 'damon:%s' % fields[4][:-1]
        trace_fields = fields[5:]
    return timestamp, proc, event, trace_fields

