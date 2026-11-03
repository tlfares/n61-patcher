#!/usr/bin/env python3
"""Record the audio driver's verified iOS 12 to iOS 13 kernel entries."""
import json
import struct

from kernel_externs import HERE, ROOT, SOURCE, TARGET, Kernel, disassemble, metaclasses


SYMBOL_MAP = {
    0xfffffff007671510: ('_memcpy', 'memcpy / memmove',
                       'Unique match after masking PC-relative fields; the first 41 instructions agree. Call arguments are dst, src and len.'),
    0xfffffff0076b4890: ('_clock_delay_until', 'clock_delay_until(deadline)',
                       'Reads cntpct_el0 and the CPU clock offset before comparing the deadline. Long waits use assert_wait/thread_block and short waits use wfe; iOS 13 thread->cpu_data offset is 0x490.'),
    0xfffffff0076b4c08: ('_clock_interval_to_deadline', 'clock_interval_to_deadline(interval,scale,out)',
                       'The nanosecond conversion constant and three arguments agree, with the result stored at [x2]. Audio passes interval=50 and scale=1000000 and stores the result at object+0x258.'),
    0xfffffff007b2c1b8: ('_kernel_debug', 'kernel_debug(debugid,arg1,arg2,arg3,arg4,arg5)',
                       'Both versions read the thread ID through tpidr_el1 into x5, set x6=0, then use the same five-event-argument framework. The iOS 13 thread ID offset is 0x440.'),
    0xfffffff007bc8178: ('_snprintf', 'snprintf(buffer,size,format,...)',
                       'The 24-instruction body retains stack varargs, character callback and terminating NUL. The call uses buffer=sp+8, size=32 and format=%s-intmic.'),
    0xfffffff007cb0ee0: ('__ZN15OSMetaClassBase9_ptmf2ptfEPKS_MS_FvvEm', 'OSMetaClassBase::_ptmf2ptf',
                       'Unique masked match of all five instructions. Audio passes a direct callback address in x1 and x2=0, then sends the result to the event-source factory.'),
    0xfffffff007cb6534: ('__ZN7OSArray12withCapacityEj', 'OSArray::withCapacity(capacity)',
                       'The iOS 12 metaclass initializer names OSArray. Both versions allocate 0x28 bytes, call initWithCapacity (iOS 12 +0xc8 / iOS 13 +0xd0), release on failure and return the object on success.'),
    0xfffffff007cb6630: ('__ZN7OSArray11withObjectsEPPK8OSObjectjj', 'OSArray::withObjects(objects,count,capacity)',
                       'Shares the OSArray vtable with withCapacity. Three arguments reach initWithObjects (iOS 12 +0xd0 / iOS 13 +0xd8); this call passes one object, count=1 and capacity=0.'),
    0xfffffff007cb920c: ('__ZN20OSCollectionIterator14withCollectionEPK12OSCollection', 'OSCollectionIterator::withCollection',
                       'The iOS 12 initializer names OSCollectionIterator. Both allocate 0x28 bytes and call initWithCollection with the collection (iOS 12 +0x88 / iOS 13 +0x90).'),
    0xfffffff007cd9b1c: ('__ZN8OSNumber10withNumberEyj', 'OSNumber::withNumber(value,bits)',
                       'The iOS 12 initializer names OSNumber. Both allocate 0x18 bytes, preserve value and bits, and call init(value,bits) (iOS 12 +0x70 / iOS 13 +0x78). Audio uses bits=64.'),
    0xfffffff007cdbfc4: ('__Znam', 'operator new[](size_t)',
                       'The 28-instruction bodies correspond block by block, allocate one byte for size=0, and account/zero after kalloc. The preceding source pair 0x7cdbf10/0x7cdbf84 is scalar new/delete.'),
    0xfffffff007cdc034: ('__ZdaPv', 'operator delete[](void*)',
                       'The complete entry matches: return for null, read allocation size, decrement the same counter and tail-call free. Paired with array allocator 0x7cdbfc4.'),
    0xfffffff007ce343c: ('__ZN8OSSymbol11withCStringEPKc', 'OSSymbol::withCString',
                       'Locks the symbol table, looks up or creates OSSymbol, copies the string and inserts it. iOS 12 calls 0x7cdff94 (allocate length+1 and memcpy); iOS 13 calls OSString::initWithCString=0x75da12c.'),
    0xfffffff007cecc44: ('__os_log_internal', '_os_log_internal(dso,log,type,format,...)',
                       'Both call sites pass Mach header, os_log, type, format and stack varargs. The iOS 13 wrapper forwards log/type/format/va_list to 0x75e33d8, retaining empty-string checks, the 0x500 filter and default-log-object checks.'),
    0xfffffff007cfc4b4: ('_IOSleep', 'IOSleep(milliseconds)',
                       'All three wrapper instructions match: w1=1000000 followed by a tail call to delay_for_interval. The iOS 13 entry is 0x75f82e4 and tail target is 0x70efbc8.'),
    0xfffffff007d1d688: ('__ZNK9IOService10isInactiveEv', 'IOService::isInactive',
                       'All eight instructions agree except the virtual slot: iOS 12 +0x290 / iOS 13 +0x298. Returns getState() & 1.'),
    0xfffffff007d33210: ('__ZN9IOService24registerInterestedDriverEPS_', 'IOService::registerInterestedDriver',
                       'Both check PM fields +0x68/+0x60/+0x38, lock +0xd8, create a capacity=4 OSSet at +0x238 and add the interested driver.'),
    0xfffffff007d33474: ('__ZN9IOService26deRegisterInterestedDriverEPS_', 'IOService::deRegisterInterestedDriver',
                       'Uses the registration function PM structure and lock; removes the driver from the +0x238 set and walks the powerInformee list under +0x38. Audio passes object+0x198 as driver.'),
    0xfffffff007d336c8: ('__ZN9IOService22acknowledgePowerChangeEPS_', 'IOService::acknowledgePowerChange',
                       'Unique masked match for the first 24 instructions. Retains driver and stores it at PM request+0x68, uses request type 0x81 and preserves the IOReturn result.'),
    0xfffffff007d44cb0: ('__ZN10IOWorkLoop8workLoopEv', 'IOWorkLoop::workLoop',
                       'The iOS 12 initializer names IOWorkLoop. Both allocate 0x48 bytes, call init (iOS 12 +0x60 / iOS 13 +0x68) and release on failure.'),
    0xfffffff007d4747c: ('__ZN22IOInterruptEventSource20interruptEventSourceEP8OSObjectPFvS1_PS_iEP9IOServicei', 'IOInterruptEventSource::interruptEventSource(owner,action,provider,index)',
                       'The iOS 12 initializer names IOInterruptEventSource. Allocates 0x68 bytes and forwards four arguments in order to init (iOS 12 +0xd0 / iOS 13 +0xd8); audio uses its provider and index=0.'),
    0xfffffff007d4e390: ('__ZN18IOTimerEventSource16timerEventSourceEP8OSObjectPFvS1_PS_E', 'IOTimerEventSource::timerEventSource(owner,action)',
                       'The iOS 12 initializer names IOTimerEventSource. Allocates 0x60 bytes, fixes options=1 and forwards owner/action to init (iOS 12 +0x138 / iOS 13 +0x140).'),
}

PLATFORM_MAP = {
    0xfffffff007e6caa0: (0xfffffff005fbe7ac, 'AppleARMPlatform::getFunction',
                       'Complete 20-instruction masked match; looks up an object by name and calls virtual slot +0x28.'),
    0xfffffff007e6f5e0: (0xfffffff005fc19c4, 'AppleARMIISDevice factory(service,provider)',
                       'Both allocate 0xc0 bytes, call IOService::C2(meta), install the AppleARMIISDevice vtable and call instanceConstructed. service/provider keep their order; init slot is iOS 12 +0x538 / iOS 13 +0x540.'),
}

CLASS_EVIDENCE = {
    0xfffffff007cb6534: (0xfffffff008a5b698, 0xfffffff00749c388, '__ZTV7OSArray'),
    0xfffffff007cb6630: (0xfffffff008a5b698, 0xfffffff00749c388, '__ZTV7OSArray'),
    0xfffffff007cb920c: (0xfffffff008a5b710, 0xfffffff00749c810, '__ZTV20OSCollectionIterator'),
    0xfffffff007cd9b1c: (0xfffffff008a5b808, 0xfffffff00749d140, '__ZTV8OSNumber'),
    0xfffffff007d44cb0: (0xfffffff008a5c6d0, 0xfffffff0074a1198, '__ZTV10IOWorkLoop'),
    0xfffffff007d4747c: (0xfffffff008a5c720, 0xfffffff0074a14c8, '__ZTV22IOInterruptEventSource'),
    0xfffffff007d4e390: (0xfffffff008a5c810, 0xfffffff0074a1e30, '__ZTV18IOTimerEventSource'),
    0xfffffff007e6f5e0: (0xfffffff008a5e668, 0xfffffff0074d3b10, None),
}


def branch_target(kernel, call):
    word = struct.unpack('<I', kernel.read(call, 4))[0]
    assert word & 0x7c000000 == 0x14000000, hex(call)
    immediate = word & 0x03ffffff
    if immediate & 0x02000000:
        immediate -= 0x04000000
    return call + immediate * 4


def main():
    source, target = Kernel(SOURCE), Kernel(TARGET)
    symbols = json.loads((HERE.parent / 'vibration/target-symbols.json').read_text())
    donor = json.loads((HERE / 'donor-code.json').read_text())
    classes = metaclasses(source, 0xfffffff007cb0d60)
    reverse = {}
    for name, address in symbols.items():
        reverse.setdefault(int(address, 16), []).append(name)
    confirmed = {}
    for entry in donor['external_branches']:
        if entry['provider'] not in ('kernel', 'com.apple.driver.AppleARMPlatform'):
            continue
        before = int(entry['target'], 16)
        if before in SYMBOL_MAP:
            symbol, identity, evidence = SYMBOL_MAP[before]
            after = int(symbols[symbol], 16)
        elif before in PLATFORM_MAP:
            after, identity, evidence = PLATFORM_MAP[before]
        else:
            previous = entry['existing_mapping']
            after, identity, evidence = int(previous['to'], 16), previous['id'], previous['how']
        for call in entry['call_sites']:
            assert branch_target(source, int(call, 16)) == before
        assert any(segment['vm'] <= after < segment['vm'] + segment['fs']
                   and 'EXEC' in segment['name'] for segment in target.segs)
        assert disassemble(target, after, 4)
        record = dict(id=identity, to=hex(after), provider=entry['provider'], how=evidence,
                      target_symbols=reverse.get(after, []), call_sites=entry['call_sites'])
        if before in CLASS_EVIDENCE:
            meta, vtable, target_vtable_symbol = CLASS_EVIDENCE[before]
            class_record = dict(source_meta=hex(meta), source_vtable=hex(vtable), **classes[meta])
            if target_vtable_symbol:
                class_record['target_vtable'] = hex(int(symbols[target_vtable_symbol], 16) + 16)
            else:
                class_record['target_meta'] = '0xfffffff0077f0530'
                class_record['target_vtable'] = '0xfffffff006dce530'
                class_record['target_initializer'] = '0xfffffff005fc313c'
            record['class_evidence'] = class_record
        confirmed[entry['target']] = record
    counts = {provider: sum(record['provider'] == provider for record in confirmed.values())
              for provider in ('kernel', 'com.apple.driver.AppleARMPlatform')}
    assert counts == {'kernel': 32, 'com.apple.driver.AppleARMPlatform': 2}
    assert confirmed['0xfffffff007cfc4b4']['to'] == '0xfffffff0075f82e4'
    report = dict(source=str(SOURCE), target=str(TARGET), counts=counts, confirmed=confirmed,
                  map={before: record['to'] for before, record in confirmed.items()}, unresolved=[],
                  iosleep=dict(source='0xfffffff007cfc4b4', target='0xfffffff0075f82e4',
                               scale=1000000, source_delay='0xfffffff0076b4a5c',
                               target_delay='0xfffffff0070efbc8'))
    (HERE / 'kernel-extern-map.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps(dict(counts=counts, unresolved=report['unresolved'], output=str(HERE / 'kernel-extern-map.json'))))


if __name__ == '__main__':
    main()
