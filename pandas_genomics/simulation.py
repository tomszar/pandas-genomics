from enum import Enum
from typing import Optional, Tuple, Union

import numpy as np
import pandas as pd

from pandas_genomics.arrays import GenotypeArray, GenotypeDtype
from pandas_genomics.scalars import Variant

# TODO: Penbase/Pendiff
# TODO: Quant Outcome Sim
# TODO: SNR


class SNPEffectEncodings(Enum):
    """Normalized SNP Effects encoded as 3-length tuples"""
    DOMINANT = (0, 1, 1)
    SUPER_ADDITIVE = (0, 0.75, 1)
    ADDITIVE = (0, 0.5, 1)
    SUB_ADDITIVE = (0, 0.25, 1)
    RECESSIVE = (0, 0, 1)
    HET = (0, 1, 0)


class BialleleicSimulation:
    """
    Used to simulate two SNPs with phenotype data based on a penetrance table.
    """
    def __init__(self,
                 pen_table: np.array = np.array([[0.0, 0.0, 1.0], [0.0, 0.0, 1.0], [1.0, 1.0, 2.0]]),
                 snp1: Optional[Variant] = None,
                 snp2: Optional[Variant] = None,
                 random_seed: int = 1855):
        pen_table, snp1, snp2 = self._validate_params(pen_table, snp1, snp2)
        self.pen_table = pen_table
        self.snp1 = snp1
        self.snp2 = snp2
        self.random_seed = random_seed

    def __str__(self):
        # TODO: Print pen_table with allele labels
        pen_table_df = pd.DataFrame(self.pen_table)
        pen_table_df.columns = _get_genotype_strs(self.snp1)
        pen_table_df.index = _get_genotype_strs(self.snp2)
        return f"SNP1 = {str(self.snp1)}\n" \
               f"SNP2 = {str(self.snp2)}\n" \
               f"Penetrance Table:\n" \
               f"----------------\n" \
               f"{pen_table_df}\n" \
               f"----------------\n" \
               f"Random Seed = {self.random_seed}"

    @staticmethod
    def _validate_params(pen_table, snp1, snp2):
        # pen_table
        if pen_table.shape != (3, 3):
            raise ValueError(f"Incorrect shape for pen_table, must be 3x3")

        # SNPs
        if snp1 is None:
            snp1 = Variant(id="rs1", ref="A", alt=["a"])
        if snp2 is None:
            snp2 = Variant(id="rs2", ref="B", alt=["b"])

        if len(snp1.alt) != 1:
            raise ValueError(f"SNP1 is not Bialleleic: {snp1}")
        if len(snp2.alt) != 1:
            raise ValueError(f"SNP2 is not Bialleleic: {snp2}")

        return pen_table, snp1, snp2

    @classmethod
    def from_model(cls,
                   eff1: Union[Tuple[float, float, float], SNPEffectEncodings] = SNPEffectEncodings.RECESSIVE,
                   eff2: Union[Tuple[float, float, float], SNPEffectEncodings] = SNPEffectEncodings.RECESSIVE,
                   baseline: float = 0.0,
                   main1: float = 1.0,
                   main2: float = 1.0,
                   interaction: float = 0.0,
                   snp1: Optional[Variant] = None,
                   snp2: Optional[Variant] = None,
                   random_seed: int = 1855
                   ):
        """
        Create a BiallelicSimulation with a Penetrance Table based on a fully specified model
        y = β0 + β1(eff1) + β2(eff2) + β3(eff1*eff2)

        Parameters
        ----------
        eff1: tuple of 3 floats
            Normalized effect of SNP1
            May be passed a value from the `Effects` enum
        eff2: tuple of 3 floats
            Normalized effect of SNP2
            May be passed a value from the `Effects` enum
        baseline: float, default 0.0
            β0 in the formula
        main1: float, default 1.0
            Main effect of SNP1, β1 in the formula
        main2: float, default 1.0
            Main effect of SNP2, β2 in the formula
        interaction: float, default 0.0
            Interaction effect, β3 in the formula
        snp1: Variant, default is None
            First SNP, one will be created by default if not specified
        snp2: Variant, default is None
            Second SNP, one will be created by default if not specified
        random_seed: int, default is 1855
            Random seed used during simulation


        Returns
        -------
        BialleleicSimulation

        """
        # TODO: Add more validation
        if type(eff1) is SNPEffectEncodings:
            eff1 = eff1.value
        if type(eff2) is SNPEffectEncodings:
            eff2 = eff2.value

        # Shape effects and scale if needed
        eff1 = np.array([eff1])  # SNP1 = columns
        eff2 = np.array([eff2]).transpose()  # SNP2 = rows
        if eff1.min() != 0 or eff1.max() != 1:
            print("Scaling eff1")
            eff1 = (eff1-eff1.min()) / (eff1.max()-eff1.min())
        if eff2.min() != 0 or eff2.max() != 1:
            print("Scaling eff2")
            eff2 = (eff2-eff2.min()) / (eff2.max()-eff2.min())

        pen_table = baseline +\
                    main1*np.repeat(eff1, 3, axis=0) +\
                    main2*np.repeat(eff2, 3, axis=1) +\
                    interaction*np.outer(eff2, eff1)

        return cls(pen_table, snp1, snp2, random_seed)

    def generate_case_control(self,
                              n_cases: int = 1000,
                              n_controls: int = 1000,
                              maf1: float = 0.30,
                              maf2: float = 0.30):
        """
        Simulate genotypes with the specified number of 'case' and 'control' phenotypes

        Parameters
        ----------
        n_cases: int, default 1000
        n_controls: int, default 1000
        maf1: float, default 0.30
            Minor Allele Frequency to use for SNP1
        maf2: float, default 0.30
            Minor Allele Frequency to use for SNP2
        snr: float, default 1.0
            Signal-to-noise ratio

        Returns
        -------
        pd.Dataframe
            Dataframe with 3 columns: Outcome (categorical), SNP1 (GenotypeArray), and SNP2 (GenotypeArray)

        """
        # Validate params
        if n_cases < 1 or n_controls < 0:
            raise ValueError("Simulation must include at least one case and at least one control")

        # Scale the penetrance table to be between 0 and 1
        pen_table_min = self.pen_table.min()
        pen_table_range = self.pen_table.max() - pen_table_min
        pen_table = (self.pen_table - pen_table_min) / pen_table_range

        # TODO: Calculate min_p and p_diff from snr
        # Adjust the penetrance table
        min_p = 0.01
        p_diff = 1 - (2 * min_p)
        pen_table = min_p + pen_table * p_diff

        #                     P(Case|GT) * P(GT)
        # Bayes: P(GT|Case) = ------------------
        #                           P(Case)

        # Create table of Prob(GT) based on MAF, assuming HWE
        prob_snp1 = np.array([(1-maf1)**2, 2*maf1*(1-maf1), (maf1)**2])
        prob_snp2 = np.array([(1-maf2)**2, 2*maf2*(1-maf2), (maf2)**2]).transpose()
        prob_gt = np.outer(prob_snp2, prob_snp1)

        # Prob(Case|GT) = pen_table
        # Prob(Case) = sum(Prob(Case|GTi) * Prob(GTi) for each GT i)
        prob_case = (pen_table*prob_gt).sum()
        # Prob(GT|Case)
        prob_gt_given_case = (pen_table * prob_gt) / prob_case

        # Prob(Control|GT) = 1-pen_table
        # Prob(Control) = sum(Prob(Control|GTi) * Prob(GTi) for each GT i)
        prob_control = ((1-pen_table) * prob_gt).sum()
        # Prob(GT|Control)
        prob_gt_given_control = ((1-pen_table) * prob_gt) / prob_control



        # Generate genotypes based on the simulated cases and controls
        # Pick int index into the table (0 through 8) counted left to right then top to bottom (due to flatten())
        case_gt_table_idxs = np.random.choice(range(9), size=n_cases, p=prob_gt_given_case.flatten())
        control_gt_table_idxs = np.random.choice(range(9), size=n_controls, p=prob_gt_given_control.flatten())

        # Create flattened genotype tables for each SNP (snp1 varies by column, snp2 by row
        gt_data_snp1 = [((0, 0), np.nan), ((0, 1), np.nan), ((1, 1), np.nan)]*3
        gt_data_snp2 = [((0, 0), np.nan), ]*3 + [((0, 1), np.nan), ]*3 + [((1, 1), np.nan), ]*3

        # Create GenotypeArrays
        snp1_case_array = _get_gt_array(case_gt_table_idxs, gt_data_snp1, self.snp1)
        snp2_case_array = _get_gt_array(case_gt_table_idxs, gt_data_snp2, self.snp2)
        snp1_control_array = _get_gt_array(control_gt_table_idxs, gt_data_snp1, self.snp1)
        snp2_control_array = _get_gt_array(control_gt_table_idxs, gt_data_snp2, self.snp2)

        # TODO: Finish
        # Merge data together
        snp1 = pd.concat(snp1_case_array, snp1_control_array)

        # Generate outcome
        outcome = pd.Series(["Case"]*n_cases + ["Control"]*n_controls)\
            .astype("category")\
            .sample(frac=1)\
            .reset_index(drop=True)



def _get_genotype_strs(variant):
    """Return a list of homozygous-ref, het, and homozygous-alt"""
    return [f"{variant.ref}{variant.ref}",
            f"{variant.ref}{variant.alt[0]}",
            f"{variant.alt[0]}{variant.alt[0]}"]


def _get_gt_array(gt_table_idxs, gt_table_data, var):
    """Assemble a GenotypeArray directly from genotype data"""
    dtype = GenotypeDtype(var)
    data = np.array([gt_table_data[i] for i in gt_table_idxs], dtype=dtype._record_type)
    return GenotypeArray(values=data, dtype=dtype)