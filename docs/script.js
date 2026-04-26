async function loadDashboard() {
    try {
        
        const response = await fetch('./data.json'); 
        const data = await response.json();

        const ultimaAtualizacao = data.ultima_atualizacao; 

        const partes = ultimaAtualizacao.match(/(\d+)\/(\d+)\/(\d+) (\d+):(\d+)/);
        const dataAtual = new Date(Date.UTC(
            parseInt(partes[3]),   // ano
            parseInt(partes[2])-1, // mês (0-indexed)
            parseInt(partes[1]),   // dia
            parseInt(partes[4]),   // hora
            parseInt(partes[5])    // minuto
        ));
        const agora = new Date();
        const horasPassadas = Math.floor((agora - dataAtual) / 3600000);

        let corAviso, textoAviso;
        if (horasPassadas < 12) {
            corAviso = '#3fb950';
            textoAviso = `<i class="fas fa-circle-check"></i> Atualizado há ${horasPassadas}h`;
        } else if (horasPassadas < 24) {
            corAviso = '#d29922';
            textoAviso = `<i class="fas fa-triangle-exclamation"></i> Atualizado há ${horasPassadas}h — dados podem estar desatualizados`;
        } else {
            corAviso = '#f85149';
            textoAviso = `<i class="fas fa-circle-xmark"></i> Atualizado há ${horasPassadas}h — robô pode estar com problema!`;
        }

        const spanUpdate = document.getElementById('update-time');
        spanUpdate.innerHTML = `${ultimaAtualizacao} (UTC) · ${textoAviso}`;
        spanUpdate.style.color = corAviso;
        
        const grid = document.getElementById('dashboard-grid');
        grid.innerHTML = ''; 

        data.ativos.forEach(ativo => {
            const isUp = parseFloat(ativo.variacao) > 0;
            const card = document.createElement('div');
            card.className = 'card';
            
            card.innerHTML = `
                <div class="card-header">
                    <h2>${ativo.moeda}</h2>
                    <span>${ativo.emoji}</span>
                </div>
                <div class="price">$ ${ativo.preco}</div>
                <div class="variation ${isUp ? 'up' : 'down'}">
                    ${isUp ? '▲' : '▼'} ${ativo.variacao}% (Est. p/ amanhã)
                </div>
                <p class="confianca">
                    <i class="fas fa-chart-bar"></i> Intervalo: $${ativo.confianca_min} – $${ativo.confianca_max}
                </p>
                <p>Status: <strong>${ativo.status}</strong></p>
                <a href="./${ativo.imagem}" target="_blank" class="chart-btn">Ver Gráfico de IA</a>
            `;
            grid.appendChild(card);
        });
    } catch (error) {
        console.error("Erro ao carregar dados:", error);
        document.getElementById('dashboard-grid').innerHTML = "<p>Dados ainda não disponíveis. O robô precisa rodar uma vez!</p>";
    }
}

async function loadHistorico() {
    try {
        const response = await fetch('./historico.json');
        const historico = await response.json();

        const tbody = document.getElementById('historico-body');
        tbody.innerHTML = '';

        
        [...historico].reverse().forEach(h => {
            const tr = document.createElement('tr');
            tr.innerHTML = `
                <td>${h.data}</td>
                <td>${h.moeda}</td>
                <td>$${h.previsao.toLocaleString('pt-BR')}</td>
                <td>$${h.confianca_min.toLocaleString('pt-BR')} – $${h.confianca_max.toLocaleString('pt-BR')}</td>
                <td>${h.preco_real !== null ? '$' + h.preco_real.toLocaleString('pt-BR') : '<i class="fas fa-clock"></i> Aguardando'}</td>
                <td>${h.erro !== null ? (h.erro > 0 ? '+' : '') + h.erro.toLocaleString('pt-BR') : '-'}</td>
                <td>${h.acerto !== null ? h.acerto : '-'}</td>
            `;
            tbody.appendChild(tr);
        });
    } catch (error) {
        document.getElementById('historico-body').innerHTML = 
            '<tr><td colspan="7">Histórico ainda não disponível.</td></tr>';
    }
}

window.onload = () => {
    loadDashboard();
    loadHistorico();
};