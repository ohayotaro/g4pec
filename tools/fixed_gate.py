"""ADC-only fixed gates and non-extending trigger holdoff; no source truth input."""
from bisect import bisect_left, bisect_right
from dataclasses import dataclass
import math
from sipm_cells import keys, number


@dataclass(frozen=True)
class GateConfig:
    schema_version: int
    provenance: str
    integration_ns: float
    pretrigger_ns: float
    holdoff_ns: float

    def __post_init__(self):
        if type(self.schema_version) is not int or self.schema_version != 1:
            raise ValueError('Unsupported fixed gate schema')
        if not isinstance(self.provenance,str) or not self.provenance.strip():
            raise ValueError('Gate provenance is required')
        for k in ('integration_ns','pretrigger_ns','holdoff_ns'):
            object.__setattr__(self,k,number(getattr(self,k),k,minimum=0,strictly_positive=k!='pretrigger_ns'))
        if self.holdoff_ns < self.integration_ns+self.pretrigger_ns:
            raise ValueError('Require holdoff >= integration + pretrigger to avoid overlapping gates')

    @classmethod
    def from_dict(cls,data):
        keys(data,cls.__dataclass_fields__,'gate configuration')
        return cls(**data)


class ADCTrace:
    """Reusable threshold crossings and bin-area prefix sums for gate scans."""
    def __init__(self,samples,config):
        self.samples, self.config = samples,config
        self.left = [s['bin_start_ns'] for s in samples]
        self.right = [s['bin_end_ns'] for s in samples]
        self.values = [s['adc_code']*config.adc_lsb_mV-config.baseline_mV for s in samples]
        self.areas, self.rails = [0.],[0]
        self.crossings = []
        armed = True
        for i,(s,v) in enumerate(zip(samples,self.values)):
            self.areas.append(self.areas[-1]+v*(self.right[i]-self.left[i]))
            self.rails.append(self.rails[-1]+int(s['adc_code'] in (0,(1<<config.adc_bits)-1)))
            if armed and v >= config.threshold_mV:
                if i == 0:
                    t = s['time_ns']
                else:
                    f = (config.threshold_mV-self.values[i-1])/(v-self.values[i-1])
                    t = samples[i-1]['time_ns']+f*(s['time_ns']-samples[i-1]['time_ns'])
                self.crossings.append(t)
                armed = False
            elif not armed and v <= config.release_mV:
                armed = True
        if not all(math.isfinite(a) for a in self.areas):
            raise ValueError('ADC area overflow')

    def extract(self, gate):
        if not self.samples: return []
        result, eligible = [], -math.inf
        for t in self.crossings:
            if t < eligible: continue
            eligible = t+gate.holdoff_ns
            requested_left,requested_right = t-gate.pretrigger_ns,t+gate.integration_ns
            if not math.isfinite(eligible) or not math.isfinite(requested_right):
                raise ValueError('Gate endpoint overflow')
            left,right = max(self.left[0],requested_left),min(self.right[-1],requested_right)
            lo,hi = bisect_right(self.right,left),bisect_left(self.left,right)-1
            if hi < lo: raise ValueError('Gate contains no ADC samples')
            area = self.areas[hi+1]-self.areas[lo]
            area -= self.values[lo]*(left-self.left[lo])
            area -= self.values[hi]*(self.right[hi]-right)
            result.append({'single_id':len(result)+1,'time_ns':t,'gate_start_ns':left,'gate_end_ns':right,
                           'charge_pC':area/self.config.transimpedance_ohm,
                           'peak_mV':max(self.values[lo:hi+1]),
                           'n_crossings':bisect_left(self.crossings,right)-bisect_left(self.crossings,left),
                           'n_saturated':self.rails[hi+1]-self.rails[lo],
                           'truncated':left!=requested_left or right!=requested_right or t==self.samples[0]['time_ns']})
        return result
