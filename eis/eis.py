from keras.models import load_model
import warnings
from concise.preprocessing import encodeDNA
import pandas as pd
import numpy as np
from tqdm import tqdm
from .generic import logit

from pkg_resources import resource_filename

ACCEPTOR_INTRON = resource_filename('eis', 'models/Intron3.h5')
DONOR = resource_filename('eis', 'models/Donor.h5')
EXON = resource_filename('eis', 'models/Exon.h5')
ACCEPTOR = resource_filename('eis', 'models/Acceptor.h5')
DONOR_INTRON = resource_filename('eis', 'models/Intron5.h5')

class Eis(object):
    """ Load modules of eis model, perform prediction with inputs come from a dataloader.

    Args: 
        acceptor_intronM: acceptor intron model, score acceptor intron sequence.
        acceptorM: accetpor splice site model. Score acceptor sequence with 50bp from intron, 3bp from exon.
        exonM: exon model, score exon sequence.
        donorM: donor splice site model, score donor sequence with 13bp in the intron, 5bp in the exon.
        donor_intronM: donor intron model, score donor intron sequence.
        exon_cut_l: when extract exon feature, how many base pair to cut out at the begining of an exon
        exon_cut_r: when extract exon feature, how many base pair to cut out at the end of an exon 
           (cut out the part that is considered as acceptor site or donor site)
        acceptor_intron_cut: how many bp to cut out at the end of acceptor intron that consider as acceptor site
        donor_intron_cut: how many bp to cut out at the end of donor intron that consider as donor site
        acceptor_intron_len: what length in acceptor intron to consider for acceptor site model
        acceptor_exon_len: what length in acceptor exon to consider for acceptor site model
        donor_intron_len: what length in donor intron to consider for donor site model
        donor_exon_len: what length in donor exon to consider for donor site model
    """

    def __init__(self, 
                 acceptor_intronM=ACCEPTOR_INTRON,
                 acceptorM=ACCEPTOR,
                 exonM=EXON,
                 donorM=DONOR,
                 donor_intronM=DONOR_INTRON,
                 
                 # parameters to split the sequence
                 exon_cut_l=0,
                 exon_cut_r=0,
                 acceptor_intron_cut=6,
                 donor_intron_cut=6,
                 acceptor_intron_len=50,
                 acceptor_exon_len=3,
                 donor_exon_len=5,
                 donor_intron_len=13
                ):
        
        self.exon_cut_l = exon_cut_l
        self.exon_cut_r = exon_cut_r
        self.acceptor_intron_cut = acceptor_intron_cut
        self.donor_intron_cut = donor_intron_cut
        self.acceptor_intron_len = acceptor_intron_len
        self.acceptor_exon_len = acceptor_exon_len
        self.donor_exon_len = donor_exon_len
        self.donor_intron_len = donor_intron_len

        self.acceptor_intronM = load_model(acceptor_intronM)
        self.acceptorM = load_model(acceptorM)
        self.exonM = load_model(exonM)
        self.donorM = load_model(donorM)
        self.donor_intronM = load_model(donor_intronM)
        
    
    def predict_on_batch(self, x, **kwargs):
        ''' Use when load batch with sequence already splited. 
        This way various length sequences are padded to the same length.
        x is a batch with sequence not encoded. 
        Need to be encoded here for collate function to work
        '''
        fts = x['seq']
        acceptor_intron = encodeDNA(fts['acceptor_intron'].tolist(), seq_align="end")
        acceptor = encodeDNA(fts['acceptor'].tolist(), seq_align="end")
        exon = encodeDNA(fts['exon'].tolist(), seq_align="end")
        donor = encodeDNA(fts['donor'].tolist(), seq_align="end")
        donor_intron = encodeDNA(fts['donor_intron'].tolist(), seq_align="end")
        score = np.concatenate([self.acceptor_intronM.predict(acceptor_intron),
                               logit(self.acceptorM.predict(acceptor)),
                               self.exonM.predict(exon),
                               logit(self.donorM.predict(donor)),
                               self.donor_intronM.predict(donor_intron)], axis=1)
        return score

    
    def predict_on_unsplitted_batch(self, inputs):
        ''' Apply self.predict function to a batch. Apply to cases where sequences
        are not splited in the dataloader. Variable input lengths are not padded to the same,
        but kept the same.
        Each loop split sequence and apply the model.
        '''
        dt = pd.DataFrame.from_dict(inputs)
        pred = dt.apply(self.predict, axis=1).as_matrix()
        return pred
    
    def predict(self, x):
        ''' Use when incomming sequence is not splited. 
        In this way, sequence with different length are one-hot encoded to the same length through padding. 
        x: a sequence to split
        '''
        seq = x['seq']
        intronl_len = x['intronl_len']
        intronr_len = x['intronr_len']
        if isinstance(seq, dict):
            fts = seq
        else:
            fts = self.split(seq, intronl_len, intronr_len)
        score = pd.Series([self.acceptor_intronM.predict(fts['acceptor_intron'])[0][0],
                               logit(self.acceptorM.predict(fts['acceptor']))[0][0],
                               self.exonM.predict(fts['exon'])[0][0],
                               logit(self.donorM.predict(fts['donor']))[0][0],
                               self.donor_intronM.predict(fts['donor_intron'])[0][0]])
        return score
    
    def split(self, x, intronl_len=100, intronr_len=80):
        ''' x: a sequence to split
        '''
        lackl = self.acceptor_intron_len - intronl_len # need to pad N if left seq not enough long
        if lackl >= 0:
            x = "N"*(lackl+1) + x
            intronl_len += lackl+1
        lackr = self.donor_intron_len - intronr_len
        if lackr >= 0:
            x = x + "N"*(lackr+1)
            intronr_len += lackr + 1
        acceptor_intron = x[:intronl_len-self.acceptor_intron_cut]
        acceptor = x[(intronl_len-self.acceptor_intron_len) : (intronl_len+self.acceptor_exon_len)]
        exon = x[(intronl_len+self.exon_cut_l) : (-intronr_len-self.exon_cut_r)]
        donor = x[(-intronr_len-self.donor_exon_len) : (-intronr_len+self.donor_intron_len)]
        donor_intron = x[-intronr_len+self.donor_intron_cut:]
        if donor[self.donor_exon_len:self.donor_exon_len+2] != "GT":
            warnings.warn("None GT donor", UserWarning)
        if acceptor[self.acceptor_intron_len-2:self.acceptor_intron_len] != "AG":
            warnings.warn("None AG donor", UserWarning)
            
        return {
            "acceptor_intron": encodeDNA([acceptor_intron]),
            "acceptor": encodeDNA([acceptor]),
            "exon": encodeDNA([exon]),
            "donor": encodeDNA([donor]),
            "donor_intron": encodeDNA([donor_intron])
        }
        


def predict_all(model, dataloader, batch_size=256, assembly_fn='sum'):
    ''' TODO: multithreading
    TODO: pack into an object that has method convert predictions to a dataframe
    '''
    ID = []
    predicts = []
    exons = []
    dt_iter = dataloader.batch_iter(batch_size=batch_size)
    for x in dt_iter:
        ref_pred = model.predict_on_batch(x['inputs'])
        alt_pred = model.predict_on_batch(x['inputs_mut'])
        ID.append(x['metadata']['variant']['ID'])
        exons.append(x['metadata']['annotation'])
        pred = assembly_fn(alt_pred - ref_pred)
        predicts.append(pred.astype(str))
    ID = np.concatenate(ID)
    predicts = np.concatenate(predicts)
    exons = np.concatenate(exons)
    predicts = np.core.defchararray.add(exons, predicts)
    # predictions = dict(zip(ID, predicts))
    predictions = pd.DataFrame({'ID': ID, 'predicts': predicts})
    predictions = predictions.groupby(['ID'],as_index=False).agg(lambda x: ','.join(set(x)))
    predictions = dict(zip(predictions.ID, predictions.predicts))
    return predictions


def predict_all_table(model, 
                    dataloader, 
                    batch_size=512,
                    assembly=True,
                    split_seq=True,
                    progress=True,
                    exon_scale_factor=5.354345):
    ''' Return the prediction as a table
        exon_scale_factor: can be determined through cross validation. Default 5.354345 is a good choice.
    '''
    ID = []
    ref_pred = []
    alt_pred = []
    exons = []
    dt_iter = dataloader.batch_iter(batch_size=batch_size)
    if progress:
        dt_iter = tqdm(dt_iter)
    for x in dt_iter:
        if split_seq:
            ref_pred.append(model.predict_on_batch(x['inputs']))
            alt_pred.append(model.predict_on_batch(x['inputs_mut']))
        else:
            ref_pred.append(model.predict_on_unsplitted_batch(x['inputs']))
            alt_pred.append(model.predict_on_unsplitted_batch(x['inputs_mut']))            
        ID.append(x['metadata']['variant']['STR'])
        exons.append(x['metadata']['annotation'])
    ID = np.concatenate(ID)
    ref_pred = np.concatenate(ref_pred)
    alt_pred = np.concatenate(alt_pred)
    ref_pred = pd.DataFrame(ref_pred, columns=['EIS_ref_acceptorIntron', 
                                     'EIS_ref_acceptor',
                                    'EIS_ref_exon',
                                    'EIS_ref_donor',
                                    'EIS_ref_donorIntron'])
    alt_pred = pd.DataFrame(alt_pred, columns=['EIS_alt_acceptorIntron', 
                                     'EIS_alt_acceptor',
                                    'EIS_alt_exon',
                                    'EIS_alt_donor',
                                    'EIS_alt_donorIntron'])
    exons = np.concatenate(exons)
    pred = pd.DataFrame({'ID': ID, 'exons': exons})
    if assembly:
        ref_pred = ref_pred.as_matrix()
        alt_pred = alt_pred.as_matrix()
        X = alt_pred-ref_pred
        exon_overlap = np.logical_or(np.logical_and(X[:,1]!=0, X[:,2]!=0), np.logical_and(X[:,2]!=0, X[:,3]!=0))
        X = np.hstack([X, (X[:,2]*exon_overlap).reshape(-1,1)])
        s = exon_scale_factor
        delt_pred = np.dot(X, np.array([1,1,s,1,1,-s]))
        pred['EIS_Diff'] = delt_pred
    else:
        pred = pd.concat([pred, ref_pred, alt_pred], axis=1)
    return pred


from cyvcf2 import Writer, VCF
def writeEIS(vcf_in, vcf_out, predictions):
    vcf = VCF(vcf_in)
    vcf.add_info_to_header({'ID': 'EIS', 'Description': 
                        'EIS splice variant effect', 
                       'Type': 'Character', 
                       'Number': '.'})
    w = Writer(vcf_out, vcf)
    for var in vcf:
        pred = predictions.get(var.ID)
        if pred is not None:
            var.INFO['EIS'] = pred
        w.write_record(var)
    w.close(); vcf.close()


